"""
Test: Ixigo — Nova Act Agent
Searches ixigo.com for flights and returns results.

Run: python3 tests/test_ixigo_agent.py
NOTE: Opens a real browser window via Nova Act (~90s).
Date defaults to 7 days from today to ensure future dates.
To see the browser live, run with FAREWISE_HEADED=1.
"""

import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from agents.ixigo import IxigoAgent

log = get_logger(__name__)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def test_ixigo_search(from_city="mumbai", to_city="delhi", days_from_now=7):
    travel_date = (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    log.info("=== test_ixigo_search: %s→%s date=%s ===", from_city, to_city, travel_date)

    # Mirrors the structured dict the orchestrator builds from the planner's output.
    # filters = planner-extracted structured constraints, not raw user input.
    search_params = {
        "from_city":    from_city,
        "to_city":      to_city,
        "date":         travel_date,
        "travel_class": "economy",
        "filters": {
            "departure_window": None,
            "max_stops":        None,
            "sort_by":          "price",
        },
    }

    agent = IxigoAgent()
    log.info("Starting Nova Act browser on ixigo.com...")
    results = agent.search(**search_params)

    log.info("Received %d flights", len(results))
    for i, r in enumerate(results, 1):
        log.info("[%d] %s %s  dep=%s arr=%s dur=%s stops=%s  price=₹%s",
                 i, r.get("airline"), r.get("flight_number"),
                 r.get("departure"), r.get("arrival"), r.get("duration"),
                 r.get("stops"), r.get("price"))

    assert_ok(len(results) > 0,
              "Ixigo agent returned 0 results — check AWS credentials and workflow name")
    assert_ok(all(r.get("platform") == "ixigo" for r in results),
              "platform field must be 'ixigo'")
    assert_ok(all(r.get("price") for r in results), "Some results missing price field")

    log.info("test_ixigo_search PASSED  (%d flights)", len(results))
    return results


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("ixigo")
    log.info("Test logs also written to %s", log_path)
    results = test_ixigo_search("mumbai", "delhi", days_from_now=7)
    log.info("Full results JSON:\n%s", json.dumps(results, indent=2))
    log.info("Ixigo agent test DONE")
