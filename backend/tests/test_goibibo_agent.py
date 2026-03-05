"""
Test: Goibibo — Nova Act Agent
Searches goibibo.com for a flight and returns results.

Run: python3 tests/test_goibibo_agent.py
NOTE: Requires NOVA_ACT_API_KEY in .env. Opens a real browser window (~90s).
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
from agents.goibibo import GoibiboAgent

log = get_logger(__name__)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def test_goibibo_search(from_city="bangalore", to_city="delhi", days_from_now=7):
    travel_date = (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    log.info("=== test_goibibo_search: %s→%s date=%s ===", from_city, to_city, travel_date)

    agent = GoibiboAgent()
    log.info("Starting Nova Act browser on goibibo.com...")
    results = agent.search(from_city=from_city, to_city=to_city, date=travel_date)

    log.info("Received %d flights", len(results))
    for i, r in enumerate(results, 1):
        log.info("[%d] %s %s  dep=%s arr=%s dur=%s stops=%s  price=₹%s",
                 i, r.get("airline"), r.get("flight_number"),
                 r.get("departure"), r.get("arrival"), r.get("duration"),
                 r.get("stops"), r.get("price"))

    assert_ok(len(results) > 0,
              "Goibibo agent returned 0 results — check NOVA_ACT_API_KEY and date")
    assert_ok(all(r.get("platform") == "goibibo" for r in results),
              "platform field must be 'goibibo'")

    log.info("test_goibibo_search PASSED  (%d flights)", len(results))
    return results


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("goibibo")
    log.info("Test logs also written to %s", log_path)
    results = test_goibibo_search("bangalore", "delhi", days_from_now=7)
    log.info("Full results JSON:\n%s", json.dumps(results, indent=2))
    log.info("Goibibo agent test DONE")
