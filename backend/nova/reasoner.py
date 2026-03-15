"""
Amazon Nova Pro — Price Reasoner
Multi-variable reasoning: bank card offers + effective price calculation + winner selection.
Uses Nova Pro (the most capable reasoning model) for complex offer math.
"""

import json
import os
import re
import sys
from typing import Optional

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

log = get_logger(__name__)


class NovaReasoner:
    """
    Uses Amazon Nova Pro to:
    1. Load bank card offers for selected cards
    2. Calculate effective price after cashback / EMI discount / reward points
    3. Pick the winner (platform × card combination)
    4. Generate a human-readable explanation

    This is the "brain" that makes FareWise different from a simple price aggregator.
    """

    MODEL_ID = "us.amazon.nova-pro-v1:0"

    SYSTEM_PROMPT = """You are an expert Indian personal finance advisor specializing in
credit card offers and e-commerce pricing. You calculate the true effective price
after applying bank card cashback, EMI discounts, reward points, and platform coupons.
Always respond with valid JSON only. Be precise with numbers."""

    def __init__(self):
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
        # Load card offers database
        self._card_offers = self._load_card_offers()

    def _load_card_offers(self) -> dict:
        """Load card offers JSON from data directory."""
        try:
            data_path = os.path.join(os.path.dirname(__file__), "..", "data", "card_offers.json")
            with open(data_path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _get_offers_for_cards(self, card_ids: list[str], platform: str) -> list[dict]:
        """Get applicable offers for the given cards on a specific platform."""
        offers = []
        for card_id in card_ids:
            card_data = self._card_offers.get(card_id, {})
            platform_offers = card_data.get("offers", {}).get(platform, [])
            offers.extend([{**o, "card_id": card_id, "card_name": card_data.get("name", card_id)}
                           for o in platform_offers])
        return offers

    async def calculate_best_deal(
        self,
        results: list[dict],
        selected_cards: list[str],
        product_name: str,
    ) -> dict:
        """
        Given raw price results from agents + user's card selection,
        calculate the true effective price for each and return the winner.

        Returns:
        {
          "winner": { platform, price_raw, price_effective, saving, card_used, explanation },
          "all_results": [ { ...same fields... } ],
          "reasoning": "plain text explanation of the calculation"
        }
        """
        log.info("Calculating best deal for '%s' across %d results with cards=%s",
                 product_name, len(results), selected_cards)

        # Build offer context for each platform
        platform_offers = {}
        for result in results:
            platform = result.get("platform", "")
            platform_offers[platform] = self._get_offers_for_cards(selected_cards, platform)

        prompt = f"""You are evaluating the best deal for: {product_name}

Raw prices from each platform:
{json.dumps(results, indent=2)}

Bank card offers available (user's selected cards):
{json.dumps(platform_offers, indent=2)}

Calculate the effective price for each platform×card combination by:
1. Applying cashback percentage (reduces effective price)
2. Applying instant discount (reduces price directly)
3. Calculating EMI discount if applicable
4. Subtracting reward points value (at ₹0.25 per point for most cards)
5. Factoring in any platform coupon codes listed

Return ONLY this JSON structure:
{{
  "winner": {{
    "platform": "amazon|flipkart|makemytrip|goibibo|cleartrip",
    "price_raw": 0,
    "price_effective": 0,
    "saving_vs_max": 0,
    "saving_percentage": 0.0,
    "card_used": "card name or null",
    "card_benefit": "description of the offer applied",
    "buy_url": "url from results"
  }},
  "all_results": [
    {{
      "platform": "string",
      "price_raw": 0,
      "price_effective": 0,
      "saving": 0,
      "card_used": "string or null",
      "rank": 1
    }}
  ],
  "reasoning": "Clear 2-3 sentence explanation of why the winner is best"
}}"""

        try:
            body = {
                "schemaVersion": "messages-v1",
                "system": [{"text": self.SYSTEM_PROMPT}],
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {
                    "maxTokens": 1024,
                    "temperature": 0.1,
                },
            }

            response = self.client.invoke_model(
                modelId=self.MODEL_ID,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            result = json.loads(response["body"].read())
            text   = result["output"]["message"]["content"][0]["text"].strip()
            
            # Robust JSON extraction
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()
            else:
                text = text.strip()

            parsed = json.loads(text)
            winner = parsed.get("winner", {})
            log.info("Winner: platform=%s price_effective=₹%s card='%s'",
                     winner.get("platform"), winner.get("price_effective"), winner.get("card_used"))
            return {"success": True, **parsed}

        except Exception as e:
            # Fallback: simple min-price selection without card math
            log.error("Nova Pro reasoning failed, falling back to min-price: %s", e)
            if results:
                best = min(results, key=lambda r: r.get("price", float("inf")))
                return {
                    "success": True,
                    "winner": {
                        "platform":          best.get("platform"),
                        "price_raw":         best.get("price"),
                        "price_effective":   best.get("price"),
                        "saving_vs_max":     0,
                        "saving_percentage": 0.0,
                        "card_used":         None,
                        "card_benefit":      "Card offer data unavailable",
                        "buy_url":           best.get("url"),
                    },
                    "all_results": results,
                    "reasoning":   f"Reasoning failed ({e}). Showing lowest raw price.",
                }
            return {"success": False, "error": str(e)}

    @staticmethod
    def _baseline_price(flight: dict) -> int:
        """Python-computed effective price: best_price_after_coupon → final_price → raw price."""
        bpac = (flight.get("offers") or {}).get("best_price_after_coupon")
        if bpac is not None:
            return int(bpac)
        fp = (flight.get("offers") or {}).get("fare_details", {}).get("final_price")
        if fp is not None:
            return int(fp)
        return int(flight.get("price") or 0)

    def _build_all_results(self, flights: list[dict]) -> list[dict]:
        """Pre-rank all flights by baseline price in Python. Returns sorted all_results list."""
        ranked = sorted(flights, key=self._baseline_price)
        results = []
        for rank, f in enumerate(ranked, start=1):
            baseline = self._baseline_price(f)
            raw = int(f.get("price") or 0)
            results.append({
                "platform":       f.get("platform", ""),
                "flight_number":  f.get("flight_number", ""),
                "price_raw":      raw,
                "price_effective": baseline,
                "saving":         max(0, raw - baseline),
                "card_used":      None,
                "rank":           rank,
            })
        return results

    async def calculate_best_flight(
        self,
        flights: list[dict],
        selected_cards: list[str],
    ) -> dict:
        """
        Phase 4 reasoning — two-step approach:

        Step A (Python): Pre-rank all flights by best_price_after_coupon.
                         Build all_results with deterministic ranks 1..N.
        Step B (LLM):    Send ONLY rank-1 flight + its platform card offers.
                         Ask: can any card reduce the price further?

        Eliminates LLM ranking errors (CHECK-1 failures) entirely.
        LLM token input shrinks from N flights × full JSON to 1 flight × 1 platform.
        """
        log.info("NovaReasoner Phase 4: pre-ranking %d flights, cards=%s",
                 len(flights), selected_cards)
        for i, f in enumerate(flights):
            log.info("  [%d] %s %s  dep=%s arr=%s  price=₹%s  coupons=%d",
                     i + 1,
                     f.get("airline", "?"), f.get("flight_number", "?"),
                     f.get("departure", "?"), f.get("arrival", "?"),
                     f.get("price", "?"),
                     len((f.get("offers") or {}).get("coupons") or []))

        # ── Step A: Python pre-ranking ────────────────────────────────────────
        all_results = self._build_all_results(flights)
        rank1_entry  = all_results[0]
        rank1_fn     = rank1_entry["flight_number"]
        rank1_flight = next((f for f in flights if f.get("flight_number") == rank1_fn), flights[0])
        rank1_baseline = rank1_entry["price_effective"]

        log.info("NovaReasoner Phase 4: rank-1 = %s ₹%s (Python pre-ranked)",
                 rank1_fn, rank1_baseline)
        for r in all_results:
            log.info("  rank=%s  %s  raw=₹%s  effective=₹%s  saving=₹%s  card=%s",
                     r["rank"], r["flight_number"],
                     r["price_raw"], r["price_effective"], r["saving"], r["card_used"])

        # ── Step B: LLM — card benefit for rank-1 only ───────────────────────
        platform     = rank1_flight.get("platform", "")
        all_card_ids = list(self._card_offers.keys())
        user_card_offers = self._get_offers_for_cards(selected_cards, platform)
        all_card_offers  = self._get_offers_for_cards(all_card_ids, platform)

        prompt = f"""You are calculating the best bank card discount for ONE pre-selected winning flight.

Winning flight (rank 1 — cheapest after site coupons, pre-ranked by Python):
{json.dumps(rank1_flight, indent=2)}

Baseline price: ₹{rank1_baseline}
(This is best_price_after_coupon — already includes site coupon + convenience fee. Do NOT add any fees.)

User's bank card offers for {platform}:
{json.dumps(user_card_offers, indent=2)}

ALL available bank card offers for {platform}:
{json.dumps(all_card_offers, indent=2)}

Task: check if any of the user's bank cards reduces the baseline by a card discount.
Subtract the best applicable card discount from ₹{rank1_baseline} to get price_effective.
If no card applies, price_effective = ₹{rank1_baseline} and card_used = null.

Return ONLY this JSON:
{{
  "price_effective": 0,
  "saving_percentage": 0.0,
  "card_used": "card name or null",
  "card_benefit": "description of the offer applied, or 'No card benefit applicable'",
  "reasoning_user": "2-3 sentence explanation of the best deal with the user's cards.",
  "reasoning_friend": "ONLY if a card from ALL available offers (not the user's cards) gives a strictly lower price than the user's best result: name that exact card and the saving. If no such improvement exists in the data provided, return null. NEVER invent or mention any card not listed above."
}}"""

        try:
            body = {
                "schemaVersion": "messages-v1",
                "system": [{"text": self.SYSTEM_PROMPT}],
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {"maxTokens": 512, "temperature": 0.1},
            }

            response = self.client.invoke_model(
                modelId=self.MODEL_ID,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            result = json.loads(response["body"].read())
            text   = result["output"]["message"]["content"][0]["text"].strip()

            match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
            text  = match.group(1).strip() if match else text.strip()
            llm   = json.loads(text)

            # Safety: LLM must not return a price higher than baseline
            price_effective = min(int(llm.get("price_effective") or rank1_baseline), rank1_baseline)

            # Patch rank-1 entry with card-adjusted price
            all_results[0]["price_effective"] = price_effective
            all_results[0]["saving"]          = max(0, rank1_entry["price_raw"] - price_effective)
            all_results[0]["card_used"]        = llm.get("card_used")

            winner = {
                "platform":          rank1_flight.get("platform", ""),
                "price_raw":         rank1_entry["price_raw"],
                "price_effective":   price_effective,
                "saving_percentage": llm.get("saving_percentage", 0.0),
                "card_used":         llm.get("card_used"),
                "card_benefit":      llm.get("card_benefit", ""),
                "book_url":          (rank1_flight.get("offers") or {}).get("booking_url")
                                     or rank1_flight.get("book_url") or rank1_flight.get("booking_url") or "",
                "flight_details": {
                    "airline":   rank1_flight.get("airline", ""),
                    "departure": rank1_flight.get("departure", ""),
                    "arrival":   rank1_flight.get("arrival", ""),
                    "duration":  rank1_flight.get("duration", ""),
                    "stops":     rank1_flight.get("stops", 0),
                },
            }

            log.info("NovaReasoner Phase 4 result: winner=%s %s  price_raw=₹%s  price_effective=₹%s  card='%s'",
                     winner["flight_details"]["airline"], winner["flight_details"]["departure"],
                     winner["price_raw"], winner["price_effective"], winner["card_used"])
            log.info("NovaReasoner reasoning: %s", llm.get("reasoning_user", ""))

            return {
                "success":          True,
                "winner":           winner,
                "all_results":      all_results,
                "reasoning_user":   llm.get("reasoning_user", ""),
                "reasoning_friend": llm.get("reasoning_friend"),
            }

        except Exception as e:
            log.error("NovaReasoner Phase 4 failed, using pre-ranked result without card benefit: %s", e)
            winner = {
                "platform":          rank1_flight.get("platform", ""),
                "price_raw":         rank1_entry["price_raw"],
                "price_effective":   rank1_baseline,
                "saving_percentage": 0.0,
                "card_used":         None,
                "card_benefit":      "Card offer data unavailable",
                "book_url":          (rank1_flight.get("offers") or {}).get("booking_url")
                                     or rank1_flight.get("book_url") or rank1_flight.get("booking_url") or "",
                "flight_details": {
                    "airline":   rank1_flight.get("airline", ""),
                    "departure": rank1_flight.get("departure", ""),
                    "arrival":   rank1_flight.get("arrival", ""),
                    "duration":  rank1_flight.get("duration", ""),
                    "stops":     rank1_flight.get("stops", 0),
                },
            }
            return {
                "success":          True,
                "winner":           winner,
                "all_results":      all_results,
                "reasoning_user":   f"Showing cheapest flight by site coupon price (card reasoning unavailable: {e})",
                "reasoning_friend": None,
            }
