"""
Test: Cleartrip — Nova Act Agent
Searches cleartrip.com for a flight and returns results.

Run: python3 tests/test_cleartrip_agent.py
NOTE: Requires NOVA_ACT_API_KEY in .env. Opens a real browser window (~90s).
To see the browser live, run with FAREWISE_HEADED=1 (e.g. FAREWISE_HEADED=1 python3 tests/test_cleartrip_agent.py).
"""

import json
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from agents.cleartrip import CleartripAgent

log = get_logger(__name__)

# Production-grade schema: required fields for each flight (agent normalizes and adds platform, from_city, etc.)
REQUIRED_FLIGHT_FIELDS = (
    "airline",
    "flight_number",
    "departure",
    "arrival",
    "duration",
    "stops",
    "price",
    "url",
)
CLEARTRIP_BASE_URL = "https://www.cleartrip.com"


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def validate_flight_schema(flights: list[dict], search_date: str):
    """Validate schema, types, times, and URL for each flight. Fails fast with clear message."""
    assert_ok(len(flights) > 0, "validate_flight_schema expects at least one flight")
    search_year = search_date[:4] if search_date and len(search_date) >= 4 else None
    for i, f in enumerate(flights):
        for field in REQUIRED_FLIGHT_FIELDS:
            assert_ok(field in f, f"flight[{i}] missing required field: {field}")
        assert_ok(isinstance(f.get("price"), int), f"flight[{i}] price must be int, got {type(f.get('price'))}")
        assert_ok(isinstance(f.get("stops"), int), f"flight[{i}] stops must be int, got {type(f.get('stops'))}")
        dep = f.get("departure", "")
        assert_ok(len(dep) == 5 and ":" in dep, f"flight[{i}] departure must be HH:MM (5 chars), got {dep!r}")
        arr = f.get("arrival", "")
        assert_ok(len(arr) == 5 and ":" in arr, f"flight[{i}] arrival must be HH:MM (5 chars), got {arr!r}")
        url = (f.get("url") or "").strip()
        assert_ok(url.startswith(CLEARTRIP_BASE_URL), f"flight[{i}] url must start with {CLEARTRIP_BASE_URL!r}, got {url[:50]!r}...")
        # If URL contains a 4-digit year, it must match search year (agent fixes wrong year via _fix_url_date_if_wrong; short URLs with no year are accepted)
        if search_year and url:
            year_in_url = re.search(r"\b(20[12]\d)\b", url)
            if year_in_url:
                assert_ok(year_in_url.group(1) == search_year, f"flight[{i}] url contains year {year_in_url.group(1)!r}, expected {search_year!r}")


def test_cleartrip_search(from_city="delhi", to_city="mumbai", days_from_now=7, filters=None):
    travel_date = (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    log.info("=== test_cleartrip_search: %s→%s date=%s filters=%s ===", from_city, to_city, travel_date, filters)

    # Mirrors the structured dict the orchestrator builds from the planner's output.
    # filters = planner-extracted structured constraints, not raw user input.
    search_params = {
        "from_city":    from_city,
        "to_city":      to_city,
        "date":         travel_date,
        "travel_class": "economy",
        "filters":      filters,       # set in __main__ to simulate a planner extraction
    }

    agent = CleartripAgent()
    log.info("Starting Nova Act browser on cleartrip.com...")
    raw = agent.search(**search_params)
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
    validate_flight_schema(results, travel_date)

    log.info("test_cleartrip_search PASSED  (%d flights)", len(results))
    return raw


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("cleartrip")
    log.info("Test logs also written to %s", log_path)
    # Simulate what the planner extracts from: "morning flights Bengaluru to Hyderabad next Friday"
    filters = {
        "departure_window": ["07:00", "10:00"],
        "max_stops":        None,
        "sort_by":          "departure",
    }
    raw = test_cleartrip_search("Bengaluru", "Hyderabad", days_from_now=4, filters=filters)
    log.info("Full results JSON:\n%s", json.dumps(raw, indent=2, default=str))
    log.info("Cleartrip agent test DONE")
