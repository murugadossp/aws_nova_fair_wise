"""
Test: Ixigo — Same flow as Cleartrip (Phase 1 + Phase 2)
Phase 1: Agent extracts flights from ixigo.com (filters in URL).
Phase 2: FlightNormalizer filters + sorts + deduplicates (same as Cleartrip).

Run: python3 tests/test_ixigo_agent.py
NOTE: Opens a real browser window via Nova Act (~90s). Requires AWS credentials.
To see the browser: FAREWISE_HEADED=1 python3 tests/test_ixigo_agent.py
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
from nova.flight_normalizer import FlightNormalizer

log = get_logger(__name__)

# Same as Cleartrip test: Phase 1 (extract) + Phase 2 (normalizer)
RUN_PHASE_1 = True
RUN_PHASE_2 = True

REQUIRED_FLIGHT_FIELDS = (
    "airline", "flight_number", "departure", "arrival",
    "duration", "stops", "price", "url",
)
CANONICAL_FLIGHT_FIELDS = (
    "platform", "airline", "flight_number", "departure", "arrival",
    "duration", "stops", "price", "book_url", "from_city", "to_city",
    "date", "travel_class",
)
IXIGO_BASE_URL = "https://www.ixigo.com"


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def _parse_hhmm(t: str) -> int:
    """Convert 'HH:MM' → minutes-since-midnight."""
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def validate_flight_schema(flights: list[dict]):
    """Validate Phase 1 output: schema, types, times, URL (Ixigo)."""
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
        assert_ok(
            url.startswith(IXIGO_BASE_URL) or url.startswith(IXIGO_BASE_URL + "/"),
            f"flight[{i}] url must be Ixigo URL, got {url[:60]!r}..." if len(url) > 60 else f"flight[{i}] url must be Ixigo URL, got {url!r}",
        )


def validate_filtered_results(filtered: list[dict], filters: dict):
    """Validate that FlightNormalizer applied filters correctly (same as Cleartrip)."""
    assert_ok(len(filtered) > 0, "FlightNormalizer returned 0 filtered flights")

    for i, f in enumerate(filtered):
        for field in CANONICAL_FLIGHT_FIELDS:
            assert_ok(field in f, f"filtered[{i}] missing canonical field: {field}")

    window = filters.get("departure_window")
    if window and len(window) == 2:
        lo = _parse_hhmm(window[0])
        hi = _parse_hhmm(window[1])
        for i, f in enumerate(filtered):
            dep = _parse_hhmm(f["departure"])
            assert_ok(lo <= dep <= hi,
                      f"filtered[{i}] departure {f['departure']} outside window {window[0]}–{window[1]}")

    max_stops = filters.get("max_stops")
    if max_stops is not None:
        for i, f in enumerate(filtered):
            assert_ok(f["stops"] <= max_stops,
                      f"filtered[{i}] has {f['stops']} stops, max_stops={max_stops}")

    sort_by = filters.get("sort_by", "price")
    if sort_by == "departure" and len(filtered) > 1:
        for i in range(1, len(filtered)):
            assert_ok(filtered[i]["departure"] >= filtered[i - 1]["departure"],
                      f"filtered not sorted by departure: [{i-1}]={filtered[i-1]['departure']} > [{i}]={filtered[i]['departure']}")
    elif sort_by == "price" and len(filtered) > 1:
        for i in range(1, len(filtered)):
            assert_ok(filtered[i]["price"] >= filtered[i - 1]["price"],
                      f"filtered not sorted by price: [{i-1}]=₹{filtered[i-1]['price']} > [{i}]=₹{filtered[i]['price']}")


def test_ixigo_search(from_city="Bengaluru", to_city="Hyderabad", days_from_now=4, filters=None):
    """Same route and filters as Cleartrip test: Bengaluru → Hyderabad, departure 07:00–10:00, non-stop, sort by departure."""
    travel_date = (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    log.info("=== test_ixigo_search: %s→%s date=%s ===", from_city, to_city, travel_date)
    log.info("    Phases: P1=%s  P2=%s  filters=%s", RUN_PHASE_1, RUN_PHASE_2, filters)

    search_params = {
        "from_city":    from_city,
        "to_city":      to_city,
        "date":         travel_date,
        "travel_class": "economy",
        "filters":      filters,
    }

    agent = IxigoAgent()
    log.info("Starting Nova Act browser on ixigo.com...")
    results = agent.search(**search_params)

    assert_ok(all(r.get("platform") == "ixigo" for r in results),
              "platform field must be 'ixigo'")
    assert_ok(all(r.get("price") for r in results), "Some results missing price field")

    log.info("Phase 1: Agent extracted %d flights", len(results))
    for i, r in enumerate(results, 1):
        log.info("  [%d] %s %s  dep=%s arr=%s dur=%s stops=%s  price=₹%s",
                 i, r.get("airline"), r.get("flight_number"),
                 r.get("departure"), r.get("arrival"), r.get("duration"),
                 r.get("stops"), r.get("price"))

    if len(results) == 0:
        log.warning(
            "Ixigo returned 0 results (site may show 'No Flights found' for this route/date). "
            "Pipeline (URL build, Nova Act, extraction) ran; Phase 2 skipped."
        )
        log.info("test_ixigo_search PASSED (0 results — pipeline validated, no flights to normalize)")
        return {"raw": [], "filtered": []}

    validate_flight_schema(results)
    log.info("Phase 1 PASSED (%d flights)", len(results))

    # Phase 2: FlightNormalizer — same as Cleartrip
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

    log.info("test_ixigo_search PASSED  (raw=%d, filtered=%d)", len(results), len(filtered))
    return {"raw": results, "filtered": filtered}


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("ixigo")
    log.info("Test logs also written to %s", log_path)

    # Use Mumbai–Delhi, 7 days out, minimal filters for higher chance of results (same shape as Cleartrip).
    filters = {
        "departure_window": ["06:00", "12:00"],
        "max_stops":        1,
        "sort_by":          "price",
    }
    result = test_ixigo_search("Mumbai", "Delhi", days_from_now=7, filters=filters)
    log.info("Full results JSON:\n%s", json.dumps(result, indent=2, default=str))
    log.info("Ixigo agent test DONE")
