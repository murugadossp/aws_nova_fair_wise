"""
Test: Cleartrip — Full Pipeline
Phase 1: Agent extracts candidate flight cards from cleartrip.com
Phase 2: FlightNormalizer filters + sorts + deduplicates authoritatively (Python)
Phase 3: Offers analysis in the same browser session (optional)

Run: python3 tests/test_cleartrip_agent.py
NOTE: Requires AWS IAM credentials. Opens a real browser window (~60s).
To see the browser live: FAREWISE_HEADED=1 python3 tests/test_cleartrip_agent.py
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from agents.cleartrip import CleartripAgent
from nova.flight_normalizer import FlightNormalizer

# Load agent config for offers_top_n (supports 1-flight testing)
_CLEARTRIP_CONFIG_PATH = Path(__file__).resolve().parent.parent / "agents" / "cleartrip" / "config.yaml"
with open(_CLEARTRIP_CONFIG_PATH, encoding="utf-8") as _f:
    _CLEARTRIP_CONFIG = yaml.safe_load(_f)
OFFERS_TOP_N = _CLEARTRIP_CONFIG.get("offers_top_n", 2)

log = get_logger(__name__)

# ── Test Phases ─────────────────────────────────────────────
RUN_PHASE_1 = True       # Agent extracts ALL flights (always needed)
RUN_PHASE_2 = True       # FlightNormalizer filters + sorts + deduplicates
RUN_PHASE_3 = True       # Offers: Book → fare+coupons → traveler → fare breakdown for top N cheapest

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


def _load_time_buckets() -> list[tuple[str, int, int]]:
    raw = _CLEARTRIP_CONFIG.get("time_buckets") or []
    return [(b["label"], _parse_hhmm(b["start"]), _parse_hhmm(b["end"])) for b in raw]


def _departure_window_to_bucket_labels(window: list[str] | None) -> list[str]:
    if not window or len(window) != 2:
        return []
    try:
        lo = _parse_hhmm(window[0])
        hi = _parse_hhmm(window[1])
    except (ValueError, AttributeError, TypeError):
        return []
    labels = [label for label, start_min, end_min in _load_time_buckets() if lo < end_min and start_min <= hi]
    return labels if len(labels) != len(_load_time_buckets()) else []


def _bucket_label_for_time(hhmm: str) -> str | None:
    try:
        value = _parse_hhmm(hhmm)
    except (ValueError, AttributeError, TypeError):
        return None
    for label, start_min, end_min in _load_time_buckets():
        if start_min <= value < end_min:
            return label
    return None


def log_phase1_candidate_warnings(flights: list[dict], filters: dict | None):
    """Surface suspicious Phase 1 rows as warnings without failing the run."""
    filters = filters or {}
    selected_dep_labels = _departure_window_to_bucket_labels(filters.get("departure_window"))
    if not selected_dep_labels:
        return
    warned = 0
    for i, flight in enumerate(flights):
        dep = flight.get("departure", "")
        bucket = _bucket_label_for_time(dep)
        if bucket is None:
            warned += 1
            log.warning("Phase 1 warning: candidate[%d] has unreadable departure %r", i, dep)
        elif bucket not in selected_dep_labels:
            warned += 1
            log.warning(
                "Phase 1 warning: candidate[%d] %s %s departure=%s bucket=%s outside selected buckets=%s",
                i,
                flight.get("airline"),
                flight.get("flight_number"),
                dep,
                bucket,
                selected_dep_labels,
            )
    if warned == 0:
        log.info("Phase 1 warnings: none (all candidate departures fit selected Cleartrip buckets %s)", selected_dep_labels)


def log_telemetry_summary(telemetry: dict | None):
    """Log top-level telemetry near the start of the test output."""
    if not isinstance(telemetry, dict):
        return
    timings = telemetry.get("timings_ms", {})
    log.info(
        "Telemetry: total=%sms phase1=%sms harvest=%sms parallel=%sms workflow=%s model=%s collect_convenience_fee=%s probe_index=%s",
        timings.get("total_search_ms", "—"),
        timings.get("phase1_extract_ms", "—"),
        timings.get("harvest_total_ms", "—"),
        timings.get("offer_parallel_wall_clock_ms", "—"),
        telemetry.get("workflow_name", "—"),
        telemetry.get("model_id", "—"),
        telemetry.get("collect_convenience_fee", False),
        telemetry.get("convenience_fee_probe_index", "—"),
    )
    for i, harvest in enumerate(telemetry.get("harvest", []), 1):
        log.info(
            "  Harvest telemetry [%d]: %s %s  harvest_ms=%s",
            i,
            harvest.get("airline"),
            harvest.get("flight_number"),
            harvest.get("harvest_ms", "—"),
        )
    for i, session in enumerate(telemetry.get("offer_sessions", []), 1):
        st = session.get("timings_ms", {})
        log.info(
            "  Offer session [%d]: %s %s  fare_ms=%s coupon_ms=%s coupon_branch_ms=%s payment_branch_ms=%s wall_clock_ms=%s insurance_ms=%s skip_addons_ms=%s skip_popup_ms=%s contact_ms=%s traveller_ms=%s payment_extract_ms=%s payment_probe_ms=%s total_ms=%s probe=%s%s",
            i,
            session.get("airline"),
            session.get("flight_number"),
            st.get("fare_summary_ms", "—"),
            st.get("coupon_ms", "—"),
            st.get("coupon_branch_total_ms", "—"),
            st.get("payment_probe_branch_total_ms", "—"),
            st.get("parallel_branch_wall_clock_ms", "—"),
            st.get("insurance_continue_ms", "—"),
            st.get("skip_addons_ms", "—"),
            st.get("skip_addons_popup_ms", "—"),
            st.get("contact_continue_ms", "—"),
            st.get("traveller_continue_ms", "—"),
            st.get("payment_fare_extract_ms", "—"),
            st.get("payment_probe_ms", "—"),
            st.get("session_total_ms", "—"),
            session.get("payment_probe_enabled", False),
            f" error={session['payment_probe_error']}" if session.get("payment_probe_error") else "",
        )


# ── Phase 1 validation ─────────────────────────────────────

def validate_flight_schema(flights: list[dict]):
    """Validate Phase 1 candidate output: schema, types, times, URL."""
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

REQUIRED_COUPON_FIELDS = ("code", "description", "discount", "price_after_coupon")
REQUIRED_OFFER_FIELDS = ("flight_number", "airline", "original_price", "fare_type", "coupons", "fare_breakdown", "additional_urls")
REQUIRED_FARE_BREAKDOWN_FIELDS = ("base_fare", "taxes", "convenience_fee", "total_fare")


def validate_offers(raw: dict | list, filters: dict | None = None, filtered_flights: list[dict] | None = None):
    """Validate Phase 3: coupons + fare breakdown for each flight.
    When filtered_flights is provided, each offer must be for a flight in that list (offers use filtered list).
    """
    if not isinstance(raw, dict) or "flights" not in raw:
        log.warning("Phase 3: agent returned list (no offers dict) — offers may not have been captured")
        return

    offers = raw.get("offers_analysis", [])
    assert_ok(len(offers) > 0, "Phase 3: offers_analysis is empty — no flights processed")
    assert_ok(len(offers) <= OFFERS_TOP_N,
              f"Phase 3: offers_analysis should have at most {OFFERS_TOP_N} entries (offers_top_n={OFFERS_TOP_N})")

    # Offers must be for flights from the filtered list (respecting departure_window / max_stops)
    if filtered_flights:
        allowed = {(f.get("flight_number"), f.get("airline")) for f in filtered_flights}
        for i, entry in enumerate(offers):
            key = (entry.get("flight_number"), entry.get("airline"))
            assert_ok(key in allowed,
                     f"offers_analysis[{i}] {entry.get('flight_number')} must be in filtered list (offers use filtered flights)")

    # When departure_window is set, each offer must be for a flight within that window
    if filters and filtered_flights:
        window = filters.get("departure_window")
        if window and len(window) == 2:
            lo, hi = _parse_hhmm(window[0]), _parse_hhmm(window[1])
            dep_by_key = {(f.get("flight_number"), f.get("airline")): _parse_hhmm(f.get("departure", "00:00")) for f in filtered_flights}
            for i, entry in enumerate(offers):
                key = (entry.get("flight_number"), entry.get("airline"))
                dep = dep_by_key.get(key)
                if dep is not None:
                    assert_ok(lo <= dep <= hi,
                              f"offers_analysis[{i}] departure must be in window {window[0]}–{window[1]}")

    for i, entry in enumerate(offers):
        for field in REQUIRED_OFFER_FIELDS:
            assert_ok(field in entry,
                      f"offers_analysis[{i}] missing field: {field}")

        add_urls = entry.get("additional_urls", {})
        assert_ok(isinstance(add_urls, dict), f"offers_analysis[{i}] additional_urls must be a dict")
        assert_ok("itinerary" in add_urls, f"offers_analysis[{i}] additional_urls must contain 'itinerary'")
        if "error" not in entry and add_urls.get("itinerary"):
            url_val = add_urls["itinerary"]
            assert_ok(isinstance(url_val, str) and url_val.startswith("http"),
                      f"offers_analysis[{i}] additional_urls.itinerary must be a non-empty URL string, got {type(url_val).__name__!r}")
        if "error" not in entry and add_urls.get("payment"):
            pay_val = add_urls["payment"]
            assert_ok(isinstance(pay_val, str) and pay_val.startswith("http"),
                      f"offers_analysis[{i}] additional_urls.payment must be a URL string, got {type(pay_val).__name__!r}")

        assert_ok(isinstance(entry["original_price"], int),
                  f"offers_analysis[{i}] original_price must be int")
        assert_ok(
            isinstance(entry["fare_type"], str) and len((entry["fare_type"] or "").strip()) > 0,
            f"offers_analysis[{i}] fare_type must be a non-empty string, got {entry.get('fare_type')!r}",
        )

        coupons = entry.get("coupons", [])
        fb = entry.get("fare_breakdown", {})
        best_after = entry.get("best_price_after_coupon")
        if best_after is not None:
            assert_ok(isinstance(best_after, int) and best_after >= 0,
                      f"offers_analysis[{i}].best_price_after_coupon must be non-negative int, got {type(best_after).__name__!r}")
            if coupons:
                assert_ok(best_after == min(c["price_after_coupon"] for c in coupons),
                          f"offers_analysis[{i}].best_price_after_coupon should be min(price_after_coupon)")
        log.info("  [%d] %s %s  original=₹%d  coupons=%d  best_after=₹%s  fare_breakdown=%s%s",
                 i + 1, entry.get("airline"), entry.get("flight_number"),
                 entry.get("original_price", 0), len(coupons),
                 str(best_after) if best_after is not None else "—",
                 "yes" if fb else "empty",
                 f"  error={entry['error']}" if "error" in entry else "")

        if "error" in entry:
            continue

        for j, c in enumerate(coupons):
            for field in REQUIRED_COUPON_FIELDS:
                assert_ok(field in c,
                          f"offers_analysis[{i}].coupons[{j}] missing field: {field}")
            assert_ok(isinstance(c["discount"], int),
                      f"coupon[{j}] discount must be int")
            expected_after = max(0, entry["original_price"] - c["discount"])
            assert_ok(c["price_after_coupon"] == expected_after,
                      f"coupon[{j}] price_after_coupon mismatch: "
                      f"{c['price_after_coupon']} != max(0, original_price - discount)")
            log.info("    coupon: %s — %s  discount=₹%d  after=₹%d",
                     c.get("code"), c.get("description", "")[:50],
                     c.get("discount", 0), c.get("price_after_coupon", 0))

        # Fare breakdown validation
        if fb:
            for field in REQUIRED_FARE_BREAKDOWN_FIELDS:
                assert_ok(field in fb,
                          f"offers_analysis[{i}].fare_breakdown missing field: {field}")
            for field in REQUIRED_FARE_BREAKDOWN_FIELDS:
                assert_ok(isinstance(fb.get(field), int),
                          f"fare_breakdown.{field} must be int, got {type(fb.get(field))}")
                assert_ok(fb.get(field, -1) >= 0,
                          f"fare_breakdown.{field} must be >= 0, got {fb.get(field)}")
            assert_ok(fb["total_fare"] >= fb["base_fare"],
                      f"fare_breakdown total_fare (₹{fb['total_fare']}) must be >= base_fare (₹{fb['base_fare']})")
            log.info("    fare: base=₹%d  taxes=₹%d  conv_fee=₹%d  total=₹%d",
                     fb.get("base_fare", 0), fb.get("taxes", 0),
                     fb.get("convenience_fee", 0), fb.get("total_fare", 0))
        else:
            log.warning("    fare_breakdown is empty for %s %s",
                        entry.get("airline"), entry.get("flight_number"))


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
        telemetry = raw.get("telemetry", {})
        results = raw["flights"]
        offers_analysis = raw.get("offers_analysis", [])
    else:
        telemetry = {}
        results = raw if isinstance(raw, list) else []
        offers_analysis = []

    log_telemetry_summary(telemetry)

    log.info("Phase 1: Agent extracted %d candidate flights (non-authoritative)", len(results))
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
    log_phase1_candidate_warnings(results, filters)
    log.info("Phase 1 PASSED (%d candidate flights)", len(results))

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

    # ── Phase 3: Offers — Book → fare+coupons → traveler → fare breakdown ─
    if RUN_PHASE_3:
        log.info("Phase 3: Validating offers for top %d flight(s) (%d entries)", OFFERS_TOP_N, len(offers_analysis))
        validate_offers(raw, filters=filters, filtered_flights=filtered if RUN_PHASE_2 and filters else None)
        errors = sum(1 for o in offers_analysis if "error" in o)
        fallbacks = sum(1 for o in offers_analysis if o.get("fare_breakdown", {}).get("source") == "fallback")
        payment_urls = sum(1 for o in offers_analysis if (o.get("additional_urls", {}) or {}).get("payment"))
        if telemetry.get("collect_convenience_fee"):
            if payment_urls:
                log.info("Phase 3 payment probe: captured %d payment URL(s)", payment_urls)
            else:
                log.warning("Phase 3 payment probe: enabled but no payment URL was captured")
        if errors or fallbacks:
            log.warning("Phase 3 PARTIAL PASS (%d offers, %d errors, %d fallback fares)",
                        len(offers_analysis), errors, fallbacks)
        else:
            log.info("Phase 3 PASSED (%d flights with full coupon+fare data)", len(offers_analysis))
    else:
        log.info("Phase 3 SKIPPED (set RUN_PHASE_3 = True to enable)")

    log.info("test_cleartrip_search PASSED  (candidate=%d, filtered=%d, offers=%d)",
             len(results), len(filtered), len(offers_analysis))
    return {"telemetry": telemetry, "raw": results, "filtered": filtered, "offers_analysis": offers_analysis}


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
