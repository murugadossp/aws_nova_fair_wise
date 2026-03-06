"""
FareWise — Agent Orchestrator

Products pipeline:  Identifier → Validator → [Amazon ‖ Flipkart] → Reasoner
Travel pipeline:    Planner → [MMT ‖ Cleartrip ‖ Ixigo] → Normalizer → Reasoner

All Nova Act agents are synchronous (blocking), so they run inside a
shared ThreadPoolExecutor and are awaited via run_in_executor.
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
from agents.cleartrip import CleartripAgent
from agents.ixigo import IxigoAgent
from nova.identifier import NovaIdentifier
from nova.validator import NovaValidator
from nova.reasoner import NovaReasoner
from nova.planner import TravelPlanner
from nova.flight_normalizer import FlightNormalizer

log = get_logger(__name__)

# Shared thread pool — one worker per Nova Act agent (each opens its own browser)
_executor = ThreadPoolExecutor(max_workers=6)

# Registry of available travel agents; planner selects a subset per query
_TRAVEL_AGENTS: dict[str, type] = {
    "makemytrip": MakeMyTripAgent,
    "cleartrip":  CleartripAgent,
    "ixigo":      IxigoAgent,
}


async def _run_in_thread(fn, *args, **kwargs):
    """Run a synchronous Nova Act agent call in the shared thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))


# ── Product Orchestrator ──────────────────────────────────────────────────────

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

            # ── Step 3: Validate with Nova Multimodal (only if image provided) ─
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


# ── Travel Orchestrator ───────────────────────────────────────────────────────

class TravelOrchestrator:
    """
    Coordinates flight price comparison:

    1. TravelPlanner   (Nova Lite) — parse query, select agents, extract criteria
    2. Selected agents (Nova Act)  — run in parallel; default: MMT + Cleartrip + Ixigo
    3. FlightNormalizer (Python)   — deduplicate, unify schema, apply criteria filter
    4. NovaReasoner    (Nova Pro)  — apply card offers, pick winner, explain

    Adding a new OTA agent: register it in _TRAVEL_AGENTS above. The planner
    will automatically be able to select it once the name is in its prompt.
    """

    def __init__(self, ws: WebSocket):
        self.ws         = ws
        self.planner    = TravelPlanner()
        self.normalizer = FlightNormalizer()
        self.reasoner   = NovaReasoner()

    async def _send(self, msg: dict):
        await self.ws.send_json(msg)

    async def _run_agent(
        self,
        name: str,
        agent,
        from_city: str,
        to_city: str,
        date: str,
        travel_class: str,
        filters: Optional[dict],
    ) -> list[dict]:
        """Run one travel agent in the thread pool, stream start/done events."""
        await self._send({"type": "agent_start", "agent": name})
        try:
            result = await _run_in_thread(
                agent.search,
                from_city, to_city, date, travel_class,
                filters,
            )
            # Cleartrip can return list (extraction only) or dict with "flights" (extraction + offers).
            if isinstance(result, dict) and "flights" in result:
                flights = result["flights"]
            else:
                flights = result if isinstance(result, list) else []
            await self._send({"type": "agent_done", "agent": name, "count": len(flights)})
            return flights
        except Exception as e:
            log.error("%s agent raised exception: %s", name, e)
            await self._send({"type": "agent_done", "agent": name, "count": 0, "error": str(e)})
            return []

    async def run(
        self,
        route: dict,
        cards: list[str],
        query: Optional[str] = None,
    ):
        log.info(
            "TravelOrchestrator.run: route=%s query=%s cards=%s",
            {k: route.get(k) for k in ("from", "to", "date", "class")},
            query,
            cards,
        )
        try:
            # ── Step 1: Planner — parse query, select agents, extract filters ──
            await self._send({"type": "progress", "step": "planning",
                               "message": "Planning your search with Nova Lite…"})

            plan = await self.planner.plan(query=query, route=route)

            r            = plan["route"]
            from_city    = r["from"]  or route.get("from", "")
            to_city      = r["to"]    or route.get("to", "")
            date         = r["date"]  or route.get("date", "")
            travel_class = r["class"] or route.get("class", "economy")
            filters      = plan.get("filters") or {}
            agent_names  = [n for n in plan["agents"] if n in _TRAVEL_AGENTS]

            log.info(
                "Plan: %s→%s date=%s class=%s agents=%s filters=%s",
                from_city, to_city, date, travel_class, agent_names, filters,
            )

            await self._send({
                "type":    "plan",
                "route":   {"from": from_city, "to": to_city, "date": date, "class": travel_class},
                "agents":  agent_names,
                "filters": filters,
            })

            # ── Step 2: Run selected agents in parallel ───────────────────────
            n = len(agent_names)
            await self._send({
                "type":    "progress",
                "step":    "searching",
                "message": f"Searching {from_city} → {to_city} across {n} platform{'s' if n != 1 else ''}…",
            })

            coros = [
                self._run_agent(
                    name, _TRAVEL_AGENTS[name](),
                    from_city, to_city, date, travel_class, filters,
                )
                for name in agent_names
            ]
            gathered = await asyncio.gather(*coros, return_exceptions=True)

            # Flatten results; exceptions already logged inside _run_agent
            raw_flights: list[dict] = []
            for item in gathered:
                if isinstance(item, list):
                    raw_flights.extend(item)
                elif isinstance(item, Exception):
                    log.error("Unexpected exception in gathered results: %s", item)

            log.info("Gathered %d raw flights from %d agents", len(raw_flights), n)

            if not raw_flights:
                await self._send({"type": "error", "message": "No flights found for this route and date."})
                return

            # ── Step 3: Normalize — dedup, unify schema, apply filters ────────
            await self._send({"type": "progress", "step": "normalizing",
                               "message": "Deduplicating and normalising flight data…"})

            flights = self.normalizer.normalize(raw_flights, filters=filters)

            if not flights:
                await self._send({"type": "error",
                                   "message": "No flights matched your criteria. Try broadening your search."})
                return

            # ── Step 4: Rank — Nova Pro applies card offers, picks winner ─────
            await self._send({"type": "progress", "step": "ranking",
                               "message": "Nova Pro calculating best fare with card discounts…"})

            deal = await self.reasoner.calculate_best_flight(
                flights=flights,
                selected_cards=cards,
            )

            await self._send({
                "type":      "results",
                "route":     {"from": from_city, "to": to_city, "date": date, "class": travel_class},
                "winner":    deal.get("winner"),
                "all":       deal.get("all_results", flights),
                "reasoning": deal.get("reasoning"),
            })

            log.info("TravelOrchestrator completed: winner=%s", deal.get("winner", {}).get("platform"))
            await self._send({"type": "done"})

        except Exception as e:
            log.error("TravelOrchestrator unhandled exception: %s", e)
            await self._send({"type": "error", "message": f"Flight search failed: {str(e)}"})
