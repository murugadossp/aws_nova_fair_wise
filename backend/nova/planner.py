"""
TravelPlanner — Nova Lite powered query planner.

Parses a natural-language travel query (or refines a structured route) into
a canonical plan: which agents to run, what criteria to apply, and a clean route.

Input:  raw user query string  (e.g. "Mumbai to Delhi this Friday morning")
        OR a pre-structured route dict from the frontend (e.g. from the sidepanel form)
Output: PlanResult dict — route + agent list + optional criteria string

Available agents: makemytrip, cleartrip, ixigo
Default: all three (safe fallback if planner fails or no query is given)
"""

import json
import os
import re
import sys
from datetime import date, timedelta
from typing import Optional

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

log = get_logger(__name__)

ALL_AGENTS = ["makemytrip", "cleartrip", "ixigo"]

# Canonical city → IATA mapping (shared reference)
CITY_CODES = {
    "mumbai": "BOM", "delhi": "DEL", "bangalore": "BLR", "bengaluru": "BLR",
    "hyderabad": "HYD", "chennai": "MAA", "kolkata": "CCU", "pune": "PNQ",
    "ahmedabad": "AMD", "goa": "GOI", "jaipur": "JAI", "kochi": "COK",
    "cochin": "COK", "lucknow": "LKO", "chandigarh": "IXC", "indore": "IDR",
    "bhubaneswar": "BBI", "nagpur": "NAG", "coimbatore": "CJB",
    "visakhapatnam": "VTZ", "vizag": "VTZ", "patna": "PAT", "srinagar": "SXR",
    "amritsar": "ATQ", "varanasi": "VNS", "leh": "IXL", "aurangabad": "IXU",
}


class TravelPlanner:
    """
    Uses Amazon Nova Lite to extract a clean travel plan from a user query.

    If a structured route is already provided AND no raw query exists,
    the planner just validates/fills defaults and returns all agents —
    skipping the LLM call entirely (saves ~300ms).
    """

    MODEL_ID = "us.amazon.nova-lite-v1:0"

    SYSTEM_PROMPT = (
        "You are a travel search planner for Indian domestic flights. "
        "Parse user travel queries into structured search plans. "
        "Today's date is {today}. Always respond with valid JSON only."
    )

    PLAN_PROMPT = """Parse this travel search request and extract a structured search plan.

User query: "{query}"

Return ONLY this JSON — no explanation, no markdown:
{{
  "route": {{
    "from": "departure city title-case (e.g. Mumbai)",
    "to": "destination city title-case (e.g. Delhi)",
    "date": "YYYY-MM-DD (resolve relative dates like 'this Friday', 'tomorrow')",
    "class": "economy | business | first  (default economy)"
  }},
  "filters": {{
    "departure_window": ["HH:MM", "HH:MM"] or null,
    "arrival_window": ["HH:MM", "HH:MM"] or null,
    "max_stops": 0 (default, non-stop) | 1 | 2 | null for any,
    "sort_by": "price | departure | duration  (default price)"
  }},
  "agents": ["makemytrip", "cleartrip", "ixigo"]
}}

Rules:
- departure_window: set only if user mentions departure time (e.g. "morning flight" → ["06:00","11:59"], "before 10am" → ["00:00","09:59"], "after 6pm" → ["18:00","23:59"])
- arrival_window: set only if user mentions arrival/landing time (e.g. "land by evening", "reach by 8pm" → ["18:00","23:59"])
- max_stops: default 0 (non-stop). Set null only if user explicitly asks for "connecting", "with stops", "1 stop", "2 stops", or similar
- agents: default all three; use subset only if user names a specific platform
- sort_by: "departure" if user asks to sort by time, else "price\""""

    def __init__(self):
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )

    def _fallback_plan(self, route: dict) -> dict:
        """Return a safe default plan from an existing structured route."""
        return {
            "route": {
                "from":  route.get("from", route.get("from_city", "")),
                "to":    route.get("to",   route.get("to_city", "")),
                "date":  route.get("date", ""),
                "class": route.get("class", route.get("travel_class", "economy")),
            },
            "filters": route.get("filters") or {
                "departure_window": None,
                "arrival_window":   None,
                "max_stops":        0,
                "sort_by":          "price",
            },
            "agents": ALL_AGENTS,
        }

    async def plan(
        self,
        query: Optional[str] = None,
        route: Optional[dict] = None,
    ) -> dict:
        """
        Build a travel plan.

        Args:
            query:  Raw natural-language query (optional)
            route:  Pre-structured route dict from frontend (optional)

        Returns:
            {
              "from_city": "Mumbai",
              "to_city":   "Delhi",
              "date":      "2026-03-15",
              "travel_class": "economy",
              "agents":    ["makemytrip", "cleartrip", "ixigo"],
              "criteria":  "morning flights" | None,
            }
        """
        # ── Fast path: structured route with no raw query ──────────────────────
        if route and not query:
            plan = self._fallback_plan(route)
            r = plan["route"]
            log.info(
                "TravelPlanner: structured route — skipping LLM. %s→%s date=%s agents=%s filters=%s",
                r["from"], r["to"], r["date"], plan["agents"], plan["filters"],
            )
            return plan

        # ── LLM path: parse raw query ──────────────────────────────────────────
        effective_query = query or ""
        if route:
            # Augment query with any known route fields for context
            route_hint = (
                f"{route.get('from', route.get('from_city', ''))} to "
                f"{route.get('to', route.get('to_city', ''))} on "
                f"{route.get('date', '')}"
            ).strip(" to on")
            if route_hint:
                effective_query = f"{effective_query} ({route_hint})".strip()

        log.info("TravelPlanner: parsing query='%s'", effective_query[:120])

        today_str = date.today().strftime("%Y-%m-%d")
        prompt = self.PLAN_PROMPT.format(query=effective_query)
        system = self.SYSTEM_PROMPT.format(today=today_str)

        try:
            body = {
                "schemaVersion": "messages-v1",
                "system": [{"text": system}],
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {"maxTokens": 256, "temperature": 0.1},
            }
            response = self.client.invoke_model(
                modelId=self.MODEL_ID,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            text = result["output"]["message"]["content"][0]["text"].strip()
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

            parsed = json.loads(text)

            # Validate + normalise agent list
            raw_agents = parsed.get("agents", ALL_AGENTS)
            agents = [a for a in raw_agents if a in ALL_AGENTS] or ALL_AGENTS

            raw_route = parsed.get("route", {})
            raw_filters = parsed.get("filters", {})

            plan = {
                "route": {
                    "from":  raw_route.get("from", ""),
                    "to":    raw_route.get("to", ""),
                    "date":  raw_route.get("date", ""),
                    "class": raw_route.get("class", "economy"),
                },
                "filters": {
                    "departure_window": raw_filters.get("departure_window"),      # ["HH:MM","HH:MM"] | null
                    "arrival_window":   raw_filters.get("arrival_window"),        # ["HH:MM","HH:MM"] | null
                    "max_stops":        raw_filters.get("max_stops", 0),          # 0 (default) | 1 | 2 | null
                    "sort_by":          raw_filters.get("sort_by", "price"),     # "price"|"departure"|"duration"
                },
                "agents": agents,
            }
            r = plan["route"]
            log.info(
                "TravelPlanner: %s→%s date=%s agents=%s filters=%s",
                r["from"], r["to"], r["date"], plan["agents"], plan["filters"],
            )
            return plan

        except Exception as e:
            log.warning("TravelPlanner LLM failed (%s) — falling back to structured route", e)
            if route:
                return self._fallback_plan(route)
            # Last resort: empty plan with all agents, no filters
            return {
                "route":   {"from": "", "to": "", "date": "", "class": "economy"},
                "filters": {"departure_window": None, "arrival_window": None, "max_stops": 0, "sort_by": "price"},
                "agents":  ALL_AGENTS,
            }
