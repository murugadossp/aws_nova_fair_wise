"""
Test: TravelPlanner — Nova Lite query parser
Validates that the planner correctly extracts route, agents, and criteria
from natural-language travel queries.

Run: python3 tests/test_nova_planner.py
NOTE: Requires AWS Bedrock access. Fast (~2–5s, no browser).
"""

import asyncio
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from nova.planner import TravelPlanner, ALL_AGENTS

log = get_logger(__name__)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


async def _run_tests():
    planner = TravelPlanner()

    # ── Test 1: Structured route (fast path — no LLM call) ───────────────────
    log.info("=== Test 1: structured route fast-path ===")
    route = {"from": "Mumbai", "to": "Delhi", "date": "2026-04-01", "class": "economy"}
    plan = await planner.plan(route=route)
    log.info("Plan: %s", plan)
    assert_ok(plan["route"]["from"] == "Mumbai", "route.from should be Mumbai")
    assert_ok(plan["route"]["to"] == "Delhi", "route.to should be Delhi")
    assert_ok(plan["agents"] == ALL_AGENTS, "default agents should be all three")
    assert_ok("filters" in plan, "plan must contain filters key")
    log.info("Test 1 PASSED ✓")

    # ── Test 2: Natural language query ────────────────────────────────────────
    log.info("=== Test 2: natural language query with morning window ===")
    plan2 = await planner.plan(query="flights from Bangalore to Goa next Friday morning")
    log.info("Plan: %s", plan2)
    assert_ok(plan2["route"]["from"].lower() in ("bangalore", "bengaluru"), "route.from should be Bangalore")
    assert_ok(plan2["route"]["to"].lower() == "goa", "route.to should be Goa")
    assert_ok(plan2["route"]["date"] >= date.today().strftime("%Y-%m-%d"), "date should be today or future")
    assert_ok(len(plan2["agents"]) > 0, "agents list should not be empty")
    assert_ok(all(a in ALL_AGENTS for a in plan2["agents"]), "all agents should be valid")
    filters2 = plan2.get("filters") or {}
    assert_ok(filters2.get("departure_window") is not None,
              f"morning query should set departure_window, got filters={filters2}")
    log.info("Test 2 PASSED ✓  filters=%s", filters2)

    # ── Test 3: Query with non-stop constraint ────────────────────────────────
    log.info("=== Test 3: query with non-stop constraint ===")
    plan3 = await planner.plan(query="non-stop flights Mumbai to Hyderabad tomorrow business class")
    log.info("Plan: %s", plan3)
    assert_ok(plan3["route"]["class"] in ("business", "Business"), "class should be business")
    filters3 = plan3.get("filters") or {}
    assert_ok(filters3.get("max_stops") == 0,
              f"non-stop query should set max_stops=0, got filters={filters3}")
    log.info("Test 3 PASSED ✓  filters=%s", filters3)

    log.info("=== All TravelPlanner tests PASSED ===")
    return [plan, plan2, plan3]


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("planner")
    log.info("Test logs also written to %s", log_path)
    results = asyncio.run(_run_tests())
    log.info("Full plans JSON:\n%s", json.dumps(results, indent=2, default=str))
    log.info("TravelPlanner test DONE")
