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
from session_logger import get_session_logger

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
        self.logger     = get_session_logger()

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
    ) -> dict:
        """Run one travel agent; return {flights, offers_analysis} so full filtered list + top-2 coupons are preserved."""
        await self._send({"type": "agent_start", "agent": name})
        loop = asyncio.get_running_loop()
        
        def on_progress(event: str, data: any):
            if event == "phase2_start":
                asyncio.run_coroutine_threadsafe(
                    self._send({
                        "type": "agent_phase",
                        "agent": name,
                        "phase": 2,
                        "count": len(data) if isinstance(data, list) else 0,
                        "interim_flights": data
                    }),
                    loop
                )
            elif event == "offer_extracted":
                asyncio.run_coroutine_threadsafe(
                    self._send({
                        "type": "offer_extracted",
                        "agent": name,
                        "offer": data
                    }),
                    loop
                )

        try:
            kwargs = {}
            if name in {"cleartrip", "makemytrip", "ixigo"}:
                kwargs["fetch_offers"] = True
                kwargs["on_progress"] = on_progress
                
            result = await _run_in_thread(
                agent.search,
                from_city, to_city, date, travel_class,
                filters,
                **kwargs,
            )
            # Some travel agents can return list-only results, while richer phased agents
            # return {"flights", "offers_analysis", "telemetry"}.
            if isinstance(result, dict) and "flights" in result:
                # Agents that run FlightNormalizer internally return their normalized list in "filtered"
                flights = result.get("filtered") if result.get("filtered") is not None else result["flights"]
                offers_analysis = result.get("offers_analysis")
            else:
                flights = result if isinstance(result, list) else []
                offers_analysis = None
                
            # Broadcast the raw extracted JSON data so the UI can show it for transparency
            if flights:
                raw_to_show = flights
                # Show raw data only for the flights that were picked for coupon analysis
                if offers_analysis:
                    raw_to_show = flights[:len(offers_analysis)]
                    
                await self._send({
                    "type": "raw_data",
                    "agent": name,
                    "data": raw_to_show
                })
                
            await self._send({"type": "agent_done", "agent": name, "count": len(flights)})
            return {"flights": flights, "offers_analysis": offers_analysis}
        except Exception as e:
            log.error("%s agent raised exception: %s", name, e)
            await self._send({"type": "agent_done", "agent": name, "count": 0, "error": str(e)})
            return {"flights": [], "offers_analysis": None}

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
            # agent_names  = [n for n in plan["agents"] if n in _TRAVEL_AGENTS]
            agent_names = ["ixigo"]  # Forced for Ixigo-only testing

            log.info(
                "Plan: %s→%s date=%s class=%s agents=%s filters=%s",
                from_city, to_city, date, travel_class, agent_names, filters,
            )

            # ── Create session logger for this search ──────────────────────────────
            session_id = self.logger.create_session(
                from_city=from_city,
                to_city=to_city,
                date=date,
                travel_class=travel_class,
                agents=agent_names,
                filters=filters,
            )
            log.info(f"Search session created: {session_id}")

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

            # Flatten flights from each agent; collect offers_analysis (e.g. Cleartrip top-2 with coupons)
            raw_flights: list[dict] = []
            offers_analysis: Optional[list] = None
            for item in gathered:
                if isinstance(item, Exception):
                    log.error("Unexpected exception in gathered results: %s", item)
                elif isinstance(item, dict):
                    # Use 'filtered' if available as it contains Phase 2/3 data (offers)
                    agent_flights = item.get("filtered") if item.get("filtered") else item.get("flights", [])
                    raw_flights.extend(agent_flights)
                    if item.get("offers_analysis"):
                        offers_analysis = item["offers_analysis"]

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

            # ── Step 3b: Re-rank by effective price (after coupon discounts) ────────
            # Flights were sorted by raw price in Phase 2. After offer extraction,
            # flights may have coupon data (best_price_after_coupon). Re-sort by
            # effective price to ensure Nova Pro analyzes the top deals (after coupons),
            # not just the top raw prices. This surfacing flights that might be
            # cheaper after coupons applied even if they weren't cheapest by raw price.
            def effective_price_key(f):
                # Use coupon-discounted baseline if available (from offer extraction Phase 5)
                coupon_price = f.get("offers", {}).get("best_price_after_coupon")
                return coupon_price or f.get("price") or 0

            flights.sort(key=effective_price_key)
            log.info(
                "Re-sorted %d flights by effective price (after coupons): top 3 are ₹%d, ₹%d, ₹%d",
                len(flights),
                effective_price_key(flights[0]) if len(flights) > 0 else 0,
                effective_price_key(flights[1]) if len(flights) > 1 else 0,
                effective_price_key(flights[2]) if len(flights) > 2 else 0,
            )

            # Determine how many flights to send to Nova Pro for ranking
            top_n_for_reasoning = min(5, len(flights))

            # Send UI update: show re-ranking in progress
            await self._send({"type": "progress", "step": "reranking",
                               "message": f"Re-ranking top {top_n_for_reasoning} by best deals (after coupons)…"})

            # ─ Tell frontend which flights are being analyzed for coupons (dynamic based on config)
            # This way, frontend doesn't need hardcoded limits. It adapts to backend config automatically.
            coupon_flight_ids = [f"{f.get('platform')}-{f.get('flight_number')}" for f in flights[:top_n_for_reasoning]]
            await self._send({
                "type": "coupon_analysis_scope",
                "flight_ids": coupon_flight_ids,
                "count": top_n_for_reasoning
            })

            # Log coupon analysis scope
            self.logger.log_phase(
                phase="offers_analysis_scope",
                agent="orchestrator",
                duration_ms=0,
                status="success",
                details={"flights_to_analyze": coupon_flight_ids, "count": top_n_for_reasoning}
            )

            # ── Step 4: Rank — Nova Pro applies card offers, picks winner ─────
            await self._send({"type": "progress", "step": "ranking",
                               "message": f"Analyzing card offers for {top_n_for_reasoning} flights…"})
            deal = await self.reasoner.calculate_best_flight(
                flights=flights[:top_n_for_reasoning],  # Top 5 by effective price (coupon-adjusted)
                selected_cards=cards,
            )

            # Merge LLM results back into original flights to preserve nested `offers`
            all_results_from_llm = deal.get("all_results", [])
            llm_map = {f"{r.get('platform')}-{r.get('flight_number')}": r for r in all_results_from_llm}
            
            with_coupons = []
            without_coupons = []
            
            for index, f in enumerate(flights):
                fid = f"{f.get('platform')}-{f.get('flight_number')}"
                llm_data = llm_map.get(fid, {})

                merged = {
                    **f,
                    "price_effective": llm_data.get("price_effective", f.get("price")),
                    "saving": llm_data.get("saving", 0),
                    "card_used": llm_data.get("card_used"),
                }

                if index < top_n_for_reasoning:  # Top N were sent for coupon analysis (now by effective price, not raw)
                    with_coupons.append(merged)
                else:                            # Rest are secondary flights (fare breakdown only)
                    without_coupons.append(merged)
                    
            # Sort the coupon ones by effective price to ensure winner is first
            def final_price(x):
                return x.get("price_effective") or x.get("price") or 0
                
            with_coupons.sort(key=final_price)
            without_coupons.sort(key=final_price)

            payload = {
                "type":      "results",
                "route":     {"from": from_city, "to": to_city, "date": date, "class": travel_class},
                "winner":    deal.get("winner"),
                "with_coupons": with_coupons,
                "without_coupons": without_coupons,
                "all":       with_coupons + without_coupons,
                "reasoning": deal.get("reasoning"),
                "reasoning_user": deal.get("reasoning_user"),
                "reasoning_friend": deal.get("reasoning_friend"),
            }
            # Full filtered list in "all"; top-2 with coupons in offers_analysis (Cleartrip); others in list but not analyzed
            if offers_analysis is not None:
                payload["offers_analysis"] = offers_analysis
            await self._send(payload)

            log.info("TravelOrchestrator completed: winner=%s", deal.get("winner", {}).get("platform"))

            # Finalize session with summary
            winner = deal.get("winner", {})
            self.logger.finalize_session(
                status="completed",
                summary={
                    "total_flights": len(flights),
                    "flights_analyzed": min(5, len(flights)),
                    "winner": f"{winner.get('airline')} {winner.get('flight_number')} at ₹{winner.get('price_effective')}",
                }
            )

            await self._send({"type": "done"})

        except Exception as e:
            log.error("TravelOrchestrator unhandled exception: %s", e)
            self.logger.log_error(str(e), "Unhandled exception during search", "orchestrator")
            self.logger.finalize_session(status="failed", summary={"error": str(e)})
            await self._send({"type": "error", "message": f"Flight search failed: {str(e)}"})
