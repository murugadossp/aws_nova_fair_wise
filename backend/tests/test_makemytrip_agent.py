"""
Test: MakeMyTrip — phased Nova Act flow

Run: python3 tests/test_makemytrip_agent.py
To see the browser live: FAREWISE_HEADED=1 python3 tests/test_makemytrip_agent.py
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from agents.makemytrip.agent import MakeMyTripAgent, _CONFIG
from nova.flight_normalizer import FlightNormalizer

log = get_logger(__name__)

_MMT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "agents" / "makemytrip" / "config.yaml"
with open(_MMT_CONFIG_PATH, encoding="utf-8") as _f:
    _MMT_CONFIG = yaml.safe_load(_f)
OFFERS_TOP_N = _MMT_CONFIG.get("offers_top_n", 1)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def _parse_hhmm(t: str) -> int:
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def validate_flight_schema(flights: list[dict]):
    assert_ok(len(flights) > 0, "MakeMyTrip returned 0 flights")
    for i, flight in enumerate(flights):
        assert_ok(flight.get("platform") == "makemytrip", f"flight[{i}] platform must be makemytrip")
        assert_ok(isinstance(flight.get("airline"), str) and flight["airline"], f"flight[{i}] missing airline")
        assert_ok(isinstance(flight.get("flight_number"), str) and flight["flight_number"], f"flight[{i}] missing flight_number")
        assert_ok(isinstance(flight.get("price"), int) and flight["price"] > 0, f"flight[{i}] invalid price")
        assert_ok(isinstance(flight.get("stops"), int) and flight["stops"] >= 0, f"flight[{i}] invalid stops")
        dep = flight.get("departure", "")
        arr = flight.get("arrival", "")
        assert_ok(len(dep) == 5 and ":" in dep, f"flight[{i}] departure must be HH:MM")
        assert_ok(len(arr) == 5 and ":" in arr, f"flight[{i}] arrival must be HH:MM")
        url = (flight.get("url") or "").strip()
        assert_ok(url.startswith(_CONFIG["base_url"]), f"flight[{i}] url must be absolute MakeMyTrip URL")


def validate_filtered_results(filtered: list[dict], filters: dict):
    assert_ok(len(filtered) > 0, "FlightNormalizer returned 0 filtered MakeMyTrip flights")
    for i, flight in enumerate(filtered):
        assert_ok(flight.get("platform") == "makemytrip", f"filtered[{i}] wrong platform")
        assert_ok(isinstance(flight.get("price"), int) and flight["price"] > 0, f"filtered[{i}] invalid price")
        book_url = (flight.get("book_url") or "").strip()
        assert_ok(book_url.startswith(_CONFIG["base_url"]), f"filtered[{i}] book_url must be absolute MakeMyTrip URL")

    dep_window = filters.get("departure_window")
    if dep_window and len(dep_window) == 2:
        lo = _parse_hhmm(dep_window[0])
        hi = _parse_hhmm(dep_window[1])
        for i, flight in enumerate(filtered):
            dep = _parse_hhmm(flight["departure"])
            assert_ok(lo <= dep <= hi, f"filtered[{i}] departure outside requested window")

    max_stops = filters.get("max_stops")
    if max_stops is not None:
        for i, flight in enumerate(filtered):
            assert_ok(flight["stops"] <= max_stops, f"filtered[{i}] stops exceed max_stops")


def validate_offers(offers: list[dict], filtered_flights: list[dict]):
    assert_ok(len(offers) <= OFFERS_TOP_N, f"offers_analysis should contain at most {OFFERS_TOP_N} offers")
    filtered_keys = {(f.get("airline"), f.get("flight_number")) for f in filtered_flights}
    for i, offer in enumerate(offers):
        key = (offer.get("airline"), offer.get("flight_number"))
        assert_ok(key in filtered_keys, f"offer[{i}] not present in filtered flights")
        assert_ok(isinstance(offer.get("original_price"), int) and offer["original_price"] > 0, f"offer[{i}] invalid original_price")
        assert_ok((offer.get("additional_urls", {}) or {}).get("itinerary", "").startswith("http"), f"offer[{i}] missing itinerary URL")
        fb = offer.get("fare_breakdown") or {}
        if fb:
            for field in ("base_fare", "taxes", "convenience_fee", "total_fare"):
                assert_ok(isinstance(fb.get(field), int), f"offer[{i}] fare_breakdown.{field} must be int")
        for j, coupon in enumerate(offer.get("coupons", [])):
            assert_ok(coupon.get("code"), f"offer[{i}] coupon[{j}] missing code")
            assert_ok(isinstance(coupon.get("discount"), int) and coupon["discount"] >= 0, f"offer[{i}] coupon[{j}] invalid discount")
            expected_after = max(0, offer["original_price"] - coupon["discount"])
            assert_ok(coupon.get("price_after_coupon") == expected_after, f"offer[{i}] coupon[{j}] price_after_coupon mismatch")


def log_telemetry_summary(telemetry: dict | None):
    if not isinstance(telemetry, dict):
        return
    timings = telemetry.get("timings_ms", {})
    log.info(
        "Telemetry: total=%sms phase1=%sms filters=%sms harvest=%sms parallel=%sms workflow=%s collect_convenience_fee=%s probe_index=%s",
        timings.get("total_search_ms", "—"),
        timings.get("phase1_extract_ms", "—"),
        timings.get("apply_filters_ms", "—"),
        timings.get("harvest_total_ms", "—"),
        timings.get("offer_parallel_wall_clock_ms", "—"),
        telemetry.get("workflow_name", "—"),
        telemetry.get("collect_convenience_fee", False),
        telemetry.get("convenience_fee_probe_index", "—"),
    )
    for i, harvest in enumerate(telemetry.get("harvest", []), 1):
        log.info(
            "  Harvest [%d]: %s %s harvest_ms=%s",
            i,
            harvest.get("airline"),
            harvest.get("flight_number"),
            harvest.get("harvest_ms", "—"),
        )
    for i, session in enumerate(telemetry.get("offer_sessions", []), 1):
        st = session.get("timings_ms", {})
        log.info(
            "  Offer session [%d]: %s %s fare_ms=%s coupon_ms=%s coupon_branch_ms=%s payment_branch_ms=%s wall_clock_ms=%s payment_probe_ms=%s total_ms=%s probe=%s%s",
            i,
            session.get("airline"),
            session.get("flight_number"),
            st.get("fare_summary_ms", "—"),
            st.get("coupon_ms", "—"),
            st.get("coupon_branch_total_ms", "—"),
            st.get("payment_probe_branch_total_ms", "—"),
            st.get("parallel_branch_wall_clock_ms", "—"),
            st.get("payment_probe_ms", "—"),
            st.get("session_total_ms", "—"),
            session.get("payment_probe_enabled", False),
            f" error={session['payment_probe_error']}" if session.get("payment_probe_error") else "",
        )


def test_mmt_search(from_city="mumbai", to_city="delhi", days_from_now=7, filters: dict | None = None):
    travel_date = (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")
    log.info("=== test_mmt_search: %s→%s date=%s filters=%s ===", from_city, to_city, travel_date, filters)

    effective_filters = filters or {
        "departure_window": None,
        "max_stops": None,
        "sort_by": "price",
    }

    # Log which UI filter slot will be clicked (if any) so it shows up in test output
    from agents.makemytrip.agent import MakeMyTripAgent as _MMTAgent
    dep_slot = _MMTAgent._window_to_mmt_slot(effective_filters.get("departure_window"))
    arr_slot = _MMTAgent._window_to_mmt_slot(effective_filters.get("arrival_window"))
    if dep_slot or arr_slot:
        log.info("  → UI filter: departure slot=%s  arrival slot=%s", dep_slot or "none", arr_slot or "none")

    search_params = {
        "from_city": from_city,
        "to_city": to_city,
        "date": travel_date,
        "travel_class": "economy",
        "filters": effective_filters,
        "fetch_offers": True,
    }

    agent = MakeMyTripAgent()
    log.info("Starting Nova Act browser on makemytrip.com...")
    result = agent.search(**search_params)
    assert_ok(isinstance(result, dict) and "flights" in result, "MakeMyTrip phased search must return dict with flights")

    flights = result["flights"]
    offers = result.get("offers_analysis") or []
    validate_flight_schema(flights)
    filtered = FlightNormalizer().normalize(flights, filters=effective_filters)
    validate_filtered_results(filtered, effective_filters)
    validate_offers(offers, filtered)
    log_telemetry_summary(result.get("telemetry"))

    log.info("Received %d raw flights, %d filtered flights, %d offers", len(flights), len(filtered), len(offers))
    for i, r in enumerate(flights, 1):
        log.info("[%d] %s %s dep=%s arr=%s dur=%s stops=%s price=₹%s", i, r.get("airline"), r.get("flight_number"), r.get("departure"), r.get("arrival"), r.get("duration"), r.get("stops"), r.get("price"))

    log.info("test_mmt_search PASSED")
    return {"raw": flights, "filtered": filtered, "offers_analysis": offers, "telemetry": result.get("telemetry", {})}


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("makemytrip")
    log.info("Test logs also written to %s", log_path)

    # Filter: morning departures only + non-stop, matching Cleartrip test convention.
    # departure_window ["06:00","12:00"] maps to the "6 AM to 12 PM" MMT filter button.
    test_filters = {
        "departure_window": ["06:00", "12:00"],
        "max_stops": 0,
        "sort_by": "price",
    }
    results = test_mmt_search("mumbai", "delhi", days_from_now=7, filters=test_filters)
    log.info("Full results JSON:\n%s", json.dumps(results, indent=2, default=str))
    log.info("MakeMyTrip agent test DONE")
