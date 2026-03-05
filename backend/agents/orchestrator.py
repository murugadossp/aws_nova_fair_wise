"""
FareWise — Agent Orchestrator
Runs Nova Act agents in parallel, streams progress over WebSocket,
then calls Nova Pro reasoner for the final winner selection.
"""

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import WebSocket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

from agents.amazon import AmazonAgent
from agents.flipkart import FlipkartAgent
from agents.makemytrip import MakeMyTripAgent
from agents.goibibo import GoibiboAgent
from agents.cleartrip import CleartripAgent
from nova.identifier import NovaIdentifier
from nova.validator import NovaValidator
from nova.reasoner import NovaReasoner

log = get_logger(__name__)

# Shared thread pool for Nova Act (synchronous browser agents)
_executor = ThreadPoolExecutor(max_workers=5)


async def _run_in_thread(fn, *args, **kwargs):
    """Run a synchronous Nova Act agent in the thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))


class ProductOrchestrator:
    """
    Coordinates the full product price comparison pipeline:
    1. Nova Lite  → identify product from screenshot / text
    2. Nova Multimodal → embed user image for validation
    3. Amazon + Flipkart Nova Act agents → run in parallel
    4. Nova Multimodal → validate + re-rank results
    5. Nova Pro → calculate effective prices, pick winner
    6. Stream all events over WebSocket
    """

    def __init__(self, ws: WebSocket):
        self.ws         = ws
        self.identifier = NovaIdentifier()
        self.validator  = NovaValidator()
        self.reasoner   = NovaReasoner()

    async def _send(self, msg: dict):
        """Stream a message to the connected client."""
        await self.ws.send_json(msg)

    async def run(self, query: str, image_b64: Optional[str], cards: list[str]):
        log.info("ProductOrchestrator.run: query='%s' has_image=%s cards=%s",
                 query, bool(image_b64), cards)
        try:
            # ── Step 1: Identify product ──────────────────────────────────────
            await self._send({"type": "progress", "step": "identifying",
                               "message": "Reading product details with Nova Lite…"})

            if image_b64:
                product_info = await self.identifier.identify_from_image(image_b64)
                # Embed reference image for later validation
                await self.validator.set_reference_image(image_b64)
            else:
                product_info = await self.identifier.identify_from_text(query)

            if not product_info.get("success"):
                await self._send({"type": "error",
                                   "message": "Could not identify product. Try a clearer image or type the product name."})
                return

            search_query = product_info.get("search_query", query)
            product_name = product_info.get("product_name", query)
            confidence   = product_info.get("confidence", 0.5)

            await self._send({
                "type":         "identified",
                "product_name": product_name,
                "search_query": search_query,
                "confidence":   confidence,
            })

            # ── Step 2: Run agents in parallel ───────────────────────────────
            await self._send({"type": "progress", "step": "searching",
                               "message": "Nova Act agents searching Amazon & Flipkart…"})

            amazon_agent   = AmazonAgent()
            flipkart_agent = FlipkartAgent()

            async def run_amazon():
                await self._send({"type": "agent_start", "agent": "amazon"})
                result = await _run_in_thread(amazon_agent.search, search_query)
                await self._send({"type": "agent_done", "agent": "amazon", "count": len(result)})
                return result

            async def run_flipkart():
                await self._send({"type": "agent_start", "agent": "flipkart"})
                result = await _run_in_thread(flipkart_agent.search, search_query)
                await self._send({"type": "agent_done", "agent": "flipkart", "count": len(result)})
                return result

            amazon_results, flipkart_results = await asyncio.gather(
                run_amazon(), run_flipkart(),
                return_exceptions=True,
            )

            # Collect raw results (handle exceptions gracefully)
            all_results = []
            if isinstance(amazon_results, list):
                all_results.extend(amazon_results)
            elif isinstance(amazon_results, Exception):
                log.error("Amazon agent raised exception: %s", amazon_results)
            if isinstance(flipkart_results, list):
                all_results.extend(flipkart_results)
            elif isinstance(flipkart_results, Exception):
                log.error("Flipkart agent raised exception: %s", flipkart_results)

            log.info("Combined results: %d total from both platforms", len(all_results))

            if not all_results:
                await self._send({"type": "error", "message": "No results found on Amazon or Flipkart."})
                return

            # ── Step 3: Validate with Nova Multimodal (only if we had an image) ──
            if image_b64 and self.validator._user_image_vec is not None:
                await self._send({"type": "progress", "step": "validating",
                                   "message": "Validating product match with Nova Multimodal…"})
                all_results = await self.validator.validate_results(all_results)

            # ── Step 4: Nova Pro reasons about best deal ──────────────────────
            await self._send({"type": "progress", "step": "reasoning",
                               "message": "Nova Pro calculating effective prices with card offers…"})

            deal = await self.reasoner.calculate_best_deal(
                results=all_results,
                selected_cards=cards,
                product_name=product_name,
            )

            # ── Step 5: Send final results ────────────────────────────────────
            await self._send({
                "type":       "results",
                "product":    product_info,
                "winner":     deal.get("winner"),
                "all":        deal.get("all_results", all_results),
                "reasoning":  deal.get("reasoning"),
            })

            log.info("ProductOrchestrator completed: winner=%s", deal.get("winner", {}).get("platform"))
            await self._send({"type": "done"})

        except Exception as e:
            log.error("ProductOrchestrator unhandled exception: %s", e)
            await self._send({"type": "error", "message": f"Search failed: {str(e)}"})


class TravelOrchestrator:
    """
    Coordinates flight price comparison:
    1. MMT + Goibibo + Cleartrip Nova Act agents run in parallel
    2. Nova Pro selects the winner with card offers applied
    """

    def __init__(self, ws: WebSocket):
        self.ws       = ws
        self.reasoner = NovaReasoner()

    async def _send(self, msg: dict):
        await self.ws.send_json(msg)

    async def run(self, route: dict, cards: list[str]):
        from_city    = route.get("from", "")
        to_city      = route.get("to", "")
        date         = route.get("date", "")
        travel_class = route.get("class", "economy")
        user_prompt  = route.get("user_prompt") or route.get("criteria")  # e.g. "morning flights 6am–12pm"
        log.info("TravelOrchestrator.run: %s→%s date=%s class=%s user_prompt=%s cards=%s",
                 from_city, to_city, date, travel_class, user_prompt, cards)
        try:

            await self._send({"type": "progress", "step": "searching",
                               "message": f"Searching {from_city} → {to_city} across 3 platforms…"})
            log.info("Starting parallel flight search: MMT + Goibibo + Cleartrip")

            mmt_agent       = MakeMyTripAgent()
            goibibo_agent   = GoibiboAgent()
            cleartrip_agent = CleartripAgent()

            async def run_mmt():
                await self._send({"type": "agent_start", "agent": "makemytrip"})
                result = await _run_in_thread(
                    mmt_agent.search,
                    from_city, to_city, date, travel_class,
                    **({"user_prompt": user_prompt} if user_prompt else {}),
                )
                await self._send({"type": "agent_done", "agent": "makemytrip", "count": len(result)})
                return result

            async def run_goibibo():
                await self._send({"type": "agent_start", "agent": "goibibo"})
                result = await _run_in_thread(
                    goibibo_agent.search,
                    from_city, to_city, date, travel_class,
                    **({"user_prompt": user_prompt} if user_prompt else {}),
                )
                await self._send({"type": "agent_done", "agent": "goibibo", "count": len(result)})
                return result

            async def run_cleartrip():
                await self._send({"type": "agent_start", "agent": "cleartrip"})
                result = await _run_in_thread(
                    cleartrip_agent.search,
                    from_city, to_city, date, travel_class,
                    **({"user_prompt": user_prompt} if user_prompt else {}),
                )
                count = len(result["flights"]) if isinstance(result, dict) and "flights" in result else len(result)
                await self._send({"type": "agent_done", "agent": "cleartrip", "count": count})
                return result

            mmt_results, goibibo_results, cleartrip_results = await asyncio.gather(
                run_mmt(), run_goibibo(), run_cleartrip(),
                return_exceptions=True,
            )

            all_flights = []
            cleartrip_offers = None
            for name, r in [("makemytrip", mmt_results), ("goibibo", goibibo_results), ("cleartrip", cleartrip_results)]:
                if isinstance(r, list):
                    all_flights.extend(r)
                elif isinstance(r, dict) and "flights" in r:
                    all_flights.extend(r["flights"])
                    if name == "cleartrip" and (r.get("offers_analysis") or r.get("suggestion")):
                        cleartrip_offers = {"offers_analysis": r.get("offers_analysis", []), "suggestion": r.get("suggestion", "")}
                elif isinstance(r, Exception):
                    log.error("%s agent raised exception: %s", name, r)

            log.info("Combined flight results: %d total from 3 platforms", len(all_flights))

            if not all_flights:
                await self._send({"type": "error", "message": "No flights found for this route and date."})
                return

            await self._send({"type": "progress", "step": "reasoning",
                               "message": "Nova Pro calculating best fare with card discounts…"})

            deal = await self.reasoner.calculate_best_flight(
                flights=all_flights,
                selected_cards=cards,
            )

            payload = {
                "type":      "results",
                "route":     route,
                "winner":    deal.get("winner"),
                "all":       deal.get("all_results", all_flights),
                "reasoning": deal.get("reasoning"),
            }
            if cleartrip_offers:
                payload["offers_analysis"] = cleartrip_offers.get("offers_analysis", [])
                payload["suggestion"] = cleartrip_offers.get("suggestion", "")
            await self._send(payload)

            log.info("TravelOrchestrator completed: winner=%s", deal.get("winner", {}).get("platform"))
            await self._send({"type": "done"})

        except Exception as e:
            log.error("TravelOrchestrator unhandled exception: %s", e)
            await self._send({"type": "error", "message": f"Flight search failed: {str(e)}"})
