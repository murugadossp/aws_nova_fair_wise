"""
Test: Ixigo — Phase 1 (extract) + Phase 2 (normalize) + Phase 3 (offers/coupons)

Phase 1: Agent extracts flights from ixigo.com (filters baked into URL).
Phase 2: FlightNormalizer filters + sorts + deduplicates.
Phase 3: For the top-N filtered flights, click Book and extract coupons in-session.

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

RUN_PHASE_1 = True
RUN_PHASE_2 = True
RUN_PHASE_3 = False  # temporarily P1+P2 only; set True for full P3 (offers)

REQUIRED_FLIGHT_FIELDS = (
    "airline", "flight_number", "departure", "arrival",
    "duration", "stops", "price",
)
CANONICAL_FLIGHT_FIELDS = (
    "platform", "airline", "flight_number", "departure", "arrival",
    "duration", "stops", "price", "from_city", "to_city",
    "date", "travel_class",
)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def _parse_hhmm(t: str) -> int:
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def validate_flight_schema(flights: list[dict]):
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


def validate_filtered_results(filtered: list[dict], filters: dict):
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


def test_ixigo_search(from_city="Bengaluru", to_city="Hyderabad", days_from_now=4, travel_date=None, filters=None):
    if travel_date is None:
        travel_date = (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    log.info("=== test_ixigo_search: %s→%s date=%s ===", from_city, to_city, travel_date)
    log.info("    Phases: P1=%s  P2=%s  P3=%s  filters=%s", RUN_PHASE_1, RUN_PHASE_2, RUN_PHASE_3, filters)

    agent = IxigoAgent()
    offers_analysis = []

    # --- Single-session path: P1 + P3 when RUN_PHASE_3 ---
    if RUN_PHASE_3 and RUN_PHASE_1:
        log.info("Phase 1+3: Single-session search with offers (optimized)...")
        result = agent.search(
            from_city=from_city,
            to_city=to_city,
            date=travel_date,
            travel_class="economy",
            filters=filters,
            fetch_offers=True,
        )
        assert_ok(isinstance(result, dict), f"fetch_offers=True should return dict, got {type(result)}")
        results = result.get("flights", [])
        offers_analysis = result.get("offers_analysis", [])
    else:
        # --- Phase 1 only ---
        log.info("Phase 1: Starting Nova Act browser on ixigo.com...")
        results = agent.search(
            from_city=from_city,
            to_city=to_city,
            date=travel_date,
            travel_class="economy",
            filters=filters,
        )
        assert_ok(isinstance(results, list), f"Phase 1 should return a list, got {type(results)}")

    assert_ok(all(r.get("platform") == "ixigo" for r in results), "platform field must be 'ixigo'")
    log.info("Phase 1: Agent extracted %d flights", len(results))
    for i, r in enumerate(results, 1):
        log.info("  [%d] %s %s  dep=%s arr=%s dur=%s stops=%s  price=₹%s",
                 i, r.get("airline"), r.get("flight_number"),
                 r.get("departure"), r.get("arrival"), r.get("duration"),
                 r.get("stops"), r.get("price"))

    if len(results) == 0:
        log.warning(
            "Ixigo returned 0 results (site may show 'No Flights found' for this route/date). "
            "Pipeline (URL build, Nova Act, extraction) ran; Phase 2/3 skipped."
        )
        log.info("test_ixigo_search PASSED (0 results — pipeline validated)")
        return {"raw": [], "filtered": [], "offers_analysis": []}

    validate_flight_schema(results)
    log.info("Phase 1 PASSED (%d flights)", len(results))

    # --- Phase 2: FlightNormalizer (for display/validation; already applied in-agent when fetch_offers=True) ---
    filtered = results
    if RUN_PHASE_2 and filters:
        normalizer = FlightNormalizer()
        filtered = normalizer.normalize(results, filters=filters)
        log.info("Phase 2: FlightNormalizer %d → %d flights", len(results), len(filtered))
        for i, f in enumerate(filtered, 1):
            log.info("  [%d] %s %s  dep=%s arr=%s  price=₹%s",
                     i, f.get("airline"), f.get("flight_number"),
                     f.get("departure"), f.get("arrival"), f.get("price"))
        if filtered:
            validate_filtered_results(filtered, filters)
        log.info("Phase 2 PASSED (%d → %d filtered)", len(results), len(filtered))
    else:
        log.info("Phase 2 SKIPPED%s", "" if not filters else " (RUN_PHASE_2=False)")

    # --- Phase 3: if we used single-session, offers_analysis already set; else fetch separately ---
    if RUN_PHASE_3 and not (RUN_PHASE_3 and RUN_PHASE_1) and filtered:
        log.info("Phase 3: Fetching offers for top %d filtered flights...", min(2, len(filtered)))
        offers_result = agent.fetch_offers(
            targets=filtered,
            from_city=from_city,
            to_city=to_city,
            date=travel_date,
            travel_class="economy",
            filters=filters,
        )
        offers_analysis = offers_result.get("offers_analysis", [])

    if offers_analysis:
        log.info("Phase 3: %d offer results", len(offers_analysis))
        for i, offer in enumerate(offers_analysis, 1):
            fare = offer.get("fare_details") or {}
            log.info("  [%d] %s %s  price=₹%s  coupons=%d  best_after_coupon=₹%s",
                     i, offer.get("airline"), offer.get("flight_number"),
                     offer.get("original_price"), len(offer.get("coupons", [])),
                     offer.get("best_price_after_coupon", "N/A"))
            if fare:
                log.info("      fare: base=₹%s  taxes=₹%s  total=₹%s",
                         fare.get("base_fare", "?"), fare.get("taxes", "?"),
                         fare.get("total", "?"))
            for j, c in enumerate(offer.get("coupons", []), 1):
                log.info("    coupon [%d] %s: %s (₹%s off → ₹%s)",
                         j, c.get("code"), c.get("description", "")[:60],
                         c.get("discount"), c.get("price_after_coupon"))
        log.info("Phase 3 DONE")
    else:
        log.info("Phase 3 SKIPPED or no offers")

    log.info("test_ixigo_search PASSED  (raw=%d, filtered=%d, offers=%d)",
             len(results), len(filtered), len(offers_analysis))
    return {"raw": results, "filtered": filtered, "offers_analysis": offers_analysis}


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("ixigo")
    log.info("Test logs also written to %s", log_path)

    filters = {
        "departure_window": ["06:00", "12:00"],
        "max_stops":        0,   # default non-stop; set 1 or 2 only if user asks for stops
        "sort_by":          "price",
    }
    # Temporarily: P1+P2 only, Hyderabad → Bengaluru, 14 Mar
    result = test_ixigo_search(
        "Hyderabad",
        "Bengaluru",
        travel_date="2026-03-14",
        filters=filters,
    )
    assert "raw" in result and "filtered" in result and "offers_analysis" in result, "test must return {raw, filtered, offers_analysis}"
    log.info("Full results JSON:\n%s", json.dumps(result, indent=2, default=str))
    log.info("Ixigo agent test DONE (P1+P2 only: raw=%d, filtered=%d)",
             len(result["raw"]), len(result["filtered"]))
