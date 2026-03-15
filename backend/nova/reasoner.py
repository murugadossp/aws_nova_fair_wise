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

    async def calculate_best_flight(
        self,
        flights: list[dict],
        selected_cards: list[str],
    ) -> dict:
        """Same reasoning logic but for flight results."""
        log.info("NovaReasoner Phase 4: calculating best flight across %d options, cards=%s",
                 len(flights), selected_cards)
        for i, f in enumerate(flights):
            log.info("  [%d] %s %s  dep=%s arr=%s  price=₹%s  coupons=%d",
                     i + 1,
                     f.get("airline", "?"), f.get("flight_number", "?"),
                     f.get("departure", "?"), f.get("arrival", "?"),
                     f.get("price", "?"),
                     len((f.get("offers") or {}).get("coupons") or []))

        # Build offer context
        platform_offers = {}
        all_platform_offers = {}
        all_card_ids = list(self._card_offers.keys())
        for f in flights:
            platform = f.get("platform", "")
            platform_offers[platform] = self._get_offers_for_cards(selected_cards, platform)
            all_platform_offers[platform] = self._get_offers_for_cards(all_card_ids, platform)

        prompt = f"""Evaluate the cheapest flight booking option after card offers.

Flight options:
{json.dumps(flights, indent=2)}

User's Bank card offers:
{json.dumps(platform_offers, indent=2)}

ALL available Bank card offers:
{json.dumps(all_platform_offers, indent=2)}

Calculate two things:
1. The winner using ONLY the "User's Bank card offers".
2. The absolute lowest price winner using "ALL available Bank card offers".

BASELINE PRICE CALCULATION — follow these rules exactly:
1. If a flight has `offers.best_price_after_coupon` (not null), use it as the STARTING BASELINE. This value already includes the convenience fee and the best site coupon discount.
2. If `offers.best_price_after_coupon` is null, use `offers.fare_details.final_price` as the baseline (booking-page total including convenience fee).
3. If neither is available, use `price` as a last resort.
4. CRITICAL: NEVER add `fare_details.convenience_fee` to any baseline — it is already included in `best_price_after_coupon` and `fare_details.final_price`. Adding it would double-count it.
5. Bank card discounts are subtracted from the chosen baseline. If coupon + card don't stack, pick the best single discount.

RANKING RULES:
- `rank` 1 = lowest `price_effective` (best deal). Higher ranks = worse deals.
- ALL items in `all_results` must be sorted strictly ascending by `price_effective` before assigning ranks.
- Never assign a higher rank number (e.g. rank=2) to a flight with lower `price_effective` than a flight with a lower rank number (e.g. rank=3).

Return ONLY this JSON:
{{
  "winner": {{
    "platform": "string",
    "price_raw": 0, // This must be the original flight's `price` field
    "price_effective": 0, // This must be the final price after ALL discounts (coupons + cards)
    "saving_percentage": 0.0,
    "card_used": "string or null",
    "card_benefit": "string",
    "book_url": "url",
    "flight_details": {{
      "airline": "string",
      "departure": "HH:MM",
      "arrival": "HH:MM",
      "duration": "string",
      "stops": 0
    }}
  }},
  "all_results": [
    {{
      "platform": "string",
      "flight_number": "string",
      "price_raw": 0,
      "price_effective": 0,
      "saving": 0,
      "card_used": "string or null",
      "rank": 1
    }}
  ],
  "reasoning_user": "2-3 sentence explanation of the best deal with the user's cards.",
  "reasoning_friend": "A comical 1-2 sentence suggestion to ask a friend/family member for a specific card to get the absolute lowest price (if the user doesn't have the best card). If the user already has the best card, return null."
}}
IMPORTANT: ALL fields in `all_results` MUST be populated. DO NOT omit `flight_number` as it is used for mapping.
IMPORTANT: DO NOT truncate the `all_results` list. You MUST return an item in `all_results` for EVERY SINGLE flight provided in the input. The length of `all_results` MUST exactly match the length of `Flight options`."""

        try:
            body = {
                "schemaVersion": "messages-v1",
                "system": [{"text": self.SYSTEM_PROMPT}],
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {"maxTokens": 1024, "temperature": 0.1},
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
            log.info("NovaReasoner Phase 4 result: winner=%s %s  price_raw=₹%s  price_effective=₹%s  card='%s'",
                     winner.get("flight_details", {}).get("airline", "?"),
                     winner.get("flight_details", {}).get("departure", ""),
                     winner.get("price_raw"), winner.get("price_effective"),
                     winner.get("card_used"))
            log.info("NovaReasoner reasoning: %s", parsed.get("reasoning_user", ""))
            for r in parsed.get("all_results", []):
                log.info("  rank=%s  %s  raw=₹%s  effective=₹%s  saving=₹%s  card=%s",
                         r.get("rank"), r.get("flight_number"),
                         r.get("price_raw"), r.get("price_effective"),
                         r.get("saving"), r.get("card_used"))
            return {"success": True, **parsed}

        except Exception as e:
            log.error("NovaReasoner Phase 4 failed, falling back to min-price: %s", e)
            if flights:
                best = min(flights, key=lambda f: f.get("price", float("inf")))
                return {"success": True, "winner": best, "all_results": flights,
                        "reasoning_user": f"Showing lowest raw price (reasoning error: {e})",
                        "reasoning_friend": None}
            return {"success": False, "error": str(e)}
