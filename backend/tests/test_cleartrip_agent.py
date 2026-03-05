"""
Test: Cleartrip — Nova Act Agent
Searches cleartrip.com for a flight and returns results.

Run: python3 tests/test_cleartrip_agent.py
NOTE: Requires NOVA_ACT_API_KEY in .env. Opens a real browser window (~90s).
To see the browser live, run with FAREWISE_HEADED=1 (e.g. FAREWISE_HEADED=1 python3 tests/test_cleartrip_agent.py).
"""

import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from agents.cleartrip import CleartripAgent

log = get_logger(__name__)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def test_cleartrip_search(from_city="delhi", to_city="mumbai", days_from_now=7, user_prompt=None):
    travel_date = (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    log.info("=== test_cleartrip_search: %s→%s date=%s user_prompt=%s ===", from_city, to_city, travel_date, user_prompt)

    agent = CleartripAgent()
    log.info("Starting Nova Act browser on cleartrip.com...")
    kwargs = {"from_city": from_city, "to_city": to_city, "date": travel_date}
    if user_prompt is not None:
        kwargs["user_prompt"] = user_prompt
    raw = agent.search(**kwargs)
    # Agent may return list (flights only) or dict (flights + offers_analysis + suggestion)
    if isinstance(raw, dict) and "flights" in raw:
        results = raw["flights"]
        offers_analysis = raw.get("offers_analysis", [])
        suggestion = raw.get("suggestion", "")
        if offers_analysis or suggestion:
            log.info("Offers analysis: %s", json.dumps(offers_analysis, indent=2))
            log.info("Suggestion: %s", suggestion)
    else:
        results = raw if isinstance(raw, list) else []

    log.info("Received %d flights", len(results))
    for i, r in enumerate(results, 1):
        log.info("[%d] %s %s  dep=%s arr=%s dur=%s stops=%s  price=₹%s",
                 i, r.get("airline"), r.get("flight_number"),
                 r.get("departure"), r.get("arrival"), r.get("duration"),
                 r.get("stops"), r.get("price"))

    assert_ok(len(results) > 0,
              "Cleartrip agent returned 0 results — check NOVA_ACT_API_KEY, date, or try a different route")
    assert_ok(all(r.get("platform") == "cleartrip" for r in results),
              "platform field must be 'cleartrip'")

    log.info("test_cleartrip_search PASSED  (%d flights)", len(results))
    return raw


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("cleartrip")
    log.info("Test logs also written to %s", log_path)
    # Include sort order so agent returns flights ordered by departure time (e.g. for time-window criteria)
    user_prompt = "morning flights between 7am and 10am. Sort results by departure time ascending."
    raw = test_cleartrip_search("Bengaluru", "Hyderabad", days_from_now=4, user_prompt=user_prompt)
    log.info("Full results JSON:\n%s", json.dumps(raw, indent=2, default=str))
    log.info("Cleartrip agent test DONE")
