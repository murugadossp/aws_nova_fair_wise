"""
Test: Cleartrip — Full Pipeline
Phase 1: Agent extracts ALL flights from cleartrip.com
Phase 2: FlightNormalizer filters + sorts + deduplicates (Python)
Phase 3: Offers analysis in the same browser session (optional)

Run: python3 tests/test_cleartrip_agent.py
NOTE: Requires AWS IAM credentials. Opens a real browser window (~60s).
To see the browser live: FAREWISE_HEADED=1 python3 tests/test_cleartrip_agent.py
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
from nova.flight_normalizer import FlightNormalizer

log = get_logger(__name__)

# ── Test Phases ─────────────────────────────────────────────
RUN_PHASE_1 = True       # Agent extracts ALL flights (always needed)
RUN_PHASE_2 = True       # FlightNormalizer filters + sorts + deduplicates
RUN_PHASE_3 = False      # Offers analysis in same browser session (adds ~30s)

# ── Schema constants ────────────────────────────────────────
REQUIRED_FLIGHT_FIELDS = (
    "airline", "flight_number", "departure", "arrival",
    "duration", "stops", "price", "url",
)
CANONICAL_FLIGHT_FIELDS = (
    "platform", "airline", "flight_number", "departure", "arrival",
    "duration", "stops", "price", "book_url", "from_city", "to_city",
    "date", "travel_class",
)
CLEARTRIP_BASE_URL = "https://www.cleartrip.com"


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


# ── Phase 1 validation ─────────────────────────────────────

def validate_flight_schema(flights: list[dict]):
    """Validate raw agent output: schema, types, times, URL."""
    assert_ok(len(flights) > 0, "validate_flight_schema expects at least one flight")
    for i, f in enumerate(flights):
        for field in REQUIRED_FLIGHT_FIELDS:
            assert_ok(field in f, f"flight[{i}] missing required field: {field}")
        assert_ok(isinstance(f.get("price"), int), f"flight[{i}] price must be int, got {type(f.get('price'))}")
        assert_ok(isinstance(f.get("stops"), int), f"flight[{i}] stops must be int, got {type(f.get('stops'))}")
        dep = f.get("departure", "")
        assert_ok(len(dep) == 5 and ":" in dep, f"flight[{i}] departure must be HH:MM, got {dep!r}")
        arr = f.get("arrival", "")
        assert_ok(len(arr) == 5 and ":" in arr, f"flight[{i}] arrival must be HH:MM, got {arr!r}")
        url = (f.get("url") or "").strip()
        assert_ok(url.startswith(CLEARTRIP_BASE_URL + "/flights/results?"),
                  f"flight[{i}] url must be search results URL, got {url[:60]!r}...")
        assert_ok("class=" in url,
                  f"flight[{i}] url must contain class= param, got {url[:80]!r}...")


# ── Phase 2 validation ─────────────────────────────────────

def _parse_hhmm(t: str) -> int:
    """Convert 'HH:MM' → minutes-since-midnight."""
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def validate_filtered_results(filtered: list[dict], filters: dict):
    """Validate that FlightNormalizer applied filters correctly."""
    assert_ok(len(filtered) > 0, "FlightNormalizer returned 0 filtered flights")

    # Canonical schema check (normalizer renames url→book_url, class→travel_class)
    for i, f in enumerate(filtered):
        for field in CANONICAL_FLIGHT_FIELDS:
            assert_ok(field in f, f"filtered[{i}] missing canonical field: {field}")

    # departure_window check
    window = filters.get("departure_window")
    if window and len(window) == 2:
        lo = _parse_hhmm(window[0])
        hi = _parse_hhmm(window[1])
        for i, f in enumerate(filtered):
            dep = _parse_hhmm(f["departure"])
            assert_ok(lo <= dep <= hi,
                      f"filtered[{i}] departure {f['departure']} outside window {window[0]}–{window[1]}")

    # max_stops check
    max_stops = filters.get("max_stops")
    if max_stops is not None:
        for i, f in enumerate(filtered):
            assert_ok(f["stops"] <= max_stops,
                      f"filtered[{i}] has {f['stops']} stops, max_stops={max_stops}")

    # sort order check
    sort_by = filters.get("sort_by", "price")
    if sort_by == "departure" and len(filtered) > 1:
        for i in range(1, len(filtered)):
            assert_ok(filtered[i]["departure"] >= filtered[i - 1]["departure"],
                      f"filtered not sorted by departure: [{i-1}]={filtered[i-1]['departure']} > [{i}]={filtered[i]['departure']}")
    elif sort_by == "price" and len(filtered) > 1:
        for i in range(1, len(filtered)):
            assert_ok(filtered[i]["price"] >= filtered[i - 1]["price"],
                      f"filtered not sorted by price: [{i-1}]=₹{filtered[i-1]['price']} > [{i}]=₹{filtered[i]['price']}")


# ── Phase 3 validation ─────────────────────────────────────

def validate_offers(raw: dict | list):
    """Validate offers analysis from the agent."""
    if not isinstance(raw, dict) or "flights" not in raw:
        log.warning("Phase 3: agent returned list (no offers dict) — offers may not have been captured")
        return
    offers = raw.get("offers_analysis", [])
    suggestion = raw.get("suggestion", "")
    if offers:
        log.info("  Offers (%d entries):", len(offers))
        for i, o in enumerate(offers, 1):
            log.info("    [%d] %s → ₹%s (%s)", i,
                     o.get("flight_reference", o.get("offer_name", "?")),
                     o.get("price_after_offer", "?"),
                     o.get("offer_name", "?"))
        assert_ok(all("offer_name" in o for o in offers), "offers must have offer_name")
    if suggestion:
        log.info("  Suggestion: %s", suggestion)


# ── Main test function ──────────────────────────────────────

def test_cleartrip_search(from_city="delhi", to_city="mumbai", days_from_now=7, filters=None):
    travel_date = (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    log.info("=== test_cleartrip_search: %s→%s date=%s ===", from_city, to_city, travel_date)
    log.info("    Phases: P1=%s  P2=%s  P3=%s  filters=%s",
             RUN_PHASE_1, RUN_PHASE_2, RUN_PHASE_3, filters)

    search_params = {
        "from_city":    from_city,
        "to_city":      to_city,
        "date":         travel_date,
        "travel_class": "economy",
        "filters":      filters,
        "fetch_offers": RUN_PHASE_3,
    }

    agent = CleartripAgent()
    log.info("Starting Nova Act browser on cleartrip.com...")
    raw = agent.search(**search_params)

    # ── Phase 1: Validate raw extraction ────────────────────────
    if isinstance(raw, dict) and "flights" in raw:
        results = raw["flights"]
        offers_analysis = raw.get("offers_analysis", [])
        suggestion = raw.get("suggestion", "")
    else:
        results = raw if isinstance(raw, list) else []
        offers_analysis = []
        suggestion = ""

    log.info("Phase 1: Agent extracted %d raw flights", len(results))
    for i, r in enumerate(results, 1):
        log.info("  [%d] %s %s  dep=%s arr=%s dur=%s stops=%s  price=₹%s",
                 i, r.get("airline"), r.get("flight_number"),
                 r.get("departure"), r.get("arrival"), r.get("duration"),
                 r.get("stops"), r.get("price"))

    assert_ok(len(results) > 0,
              "Cleartrip agent returned 0 results — check AWS IAM credentials, date, or route")
    assert_ok(all(r.get("platform") == "cleartrip" for r in results),
              "platform field must be 'cleartrip'")
    validate_flight_schema(results)
    log.info("Phase 1 PASSED (%d raw flights)", len(results))

    # ── Phase 2: FlightNormalizer — filter + sort + dedup ───────
    filtered = results
    if RUN_PHASE_2 and filters:
        normalizer = FlightNormalizer()
        filtered = normalizer.normalize(results, filters=filters)

        log.info("Phase 2: FlightNormalizer %d → %d flights", len(results), len(filtered))
        for i, f in enumerate(filtered, 1):
            log.info("  [%d] %s %s  dep=%s arr=%s  price=₹%s",
                     i, f.get("airline"), f.get("flight_number"),
                     f.get("departure"), f.get("arrival"), f.get("price"))

        validate_filtered_results(filtered, filters)
        log.info("Phase 2 PASSED (%d → %d filtered)", len(results), len(filtered))
    else:
        log.info("Phase 2 SKIPPED%s", "" if not filters else " (RUN_PHASE_2=False)")

    # ── Phase 3: Offers (if enabled) ────────────────────────────
    if RUN_PHASE_3:
        validate_offers(raw)
        log.info("Phase 3 PASSED")
    else:
        log.info("Phase 3 SKIPPED (set RUN_PHASE_3 = True to enable)")

    log.info("test_cleartrip_search PASSED  (raw=%d, filtered=%d)", len(results), len(filtered))
    return {"raw": results, "filtered": filtered, "offers_analysis": offers_analysis, "suggestion": suggestion}


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("cleartrip")
    log.info("Test logs also written to %s", log_path)
    filters = {
        "departure_window": ["07:00", "10:00"],
        "max_stops":        0,
        "sort_by":          "departure",
    }
    result = test_cleartrip_search("Bengaluru", "Hyderabad", days_from_now=4, filters=filters)
    log.info("Full results JSON:\n%s", json.dumps(result, indent=2, default=str))
    log.info("Cleartrip agent test DONE")
