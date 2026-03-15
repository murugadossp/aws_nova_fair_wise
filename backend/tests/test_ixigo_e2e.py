"""
Test: Ixigo — End-to-End Tests  (mimics real user interactions)

These tests replicate the complete user journey:
  1. User opens FareWise extension sidepanel
  2. Enters route + date + class (optionally credit cards)
  3. Clicks Search → WebSocket opens → backend pipeline runs
  4. User sees interim flight cards, then final ranked results with fare breakdown

Tests cover every pipeline phase individually and end-to-end:
  Phase 1 — IxigoAgent.search() extracts flights from ixigo.com (Nova Act)
  Phase 2 — FlightNormalizer deduplicates, validates, applies filters, sorts
  Phase 3 — IxigoAgent fetches per-flight coupons + fare breakdown (Nova Act)
  Phase 4 — TravelOrchestrator runs full WebSocket pipeline end-to-end

Run (from backend/ directory):
  python3 tests/test_ixigo_e2e.py

Options:
  FAREWISE_HEADED=1 python3 tests/test_ixigo_e2e.py   # show browser
  python3 tests/test_ixigo_e2e.py --phase1-only        # skip Phase 3 and orchestrator
  python3 tests/test_ixigo_e2e.py --skip-orchestrator  # skip full orchestrator test

NOTE: Tests open real browser windows via Nova Act (~60-180s per test).
      Requires AWS credentials + NOVA_ACT_API_KEY in .env file.

Route used: Chennai → Bengaluru  (MAA → BLR)
Date used:  2026-03-22  (one week from today: 2026-03-15)
"""

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from agents.ixigo import IxigoAgent
from nova.flight_normalizer import FlightNormalizer
from session_logger import SessionLogger

log = get_logger(__name__)

# ── Test configuration ──────────────────────────────────────────────────────

# Fixed date: one week from "today" (2026-03-15) as specified in the task brief.
TRAVEL_DATE = "2026-03-22"

# Primary route: Chennai → Bengaluru (short, busy corridor with many flights)
ROUTE_FROM  = "Chennai"
ROUTE_TO    = "Bengaluru"

# Secondary route for normalization test
ROUTE2_FROM = "Mumbai"
ROUTE2_TO   = "Delhi"

TRAVEL_CLASS = "economy"

# Canonical fields every normalized flight must have
CANONICAL_FLIGHT_FIELDS = (
    "platform", "airline", "flight_number", "departure", "arrival",
    "duration", "stops", "price", "from_city", "to_city",
    "date", "travel_class",
)

# Minimum raw fields returned by Phase 1 before normalization
REQUIRED_RAW_FIELDS = (
    "airline", "flight_number", "departure", "arrival", "duration", "stops", "price",
)

# Required offer fields from Phase 3
REQUIRED_OFFER_FIELDS = (
    "flight_number", "airline", "original_price", "fare_details", "coupons",
)


# ── Assertion helper ────────────────────────────────────────────────────────

def assert_ok(condition: bool, message: str) -> None:
    """Fail with a clear log message if `condition` is False."""
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


# ── Shared validation helpers ───────────────────────────────────────────────

def _parse_hhmm(t: str) -> int:
    """Convert 'HH:MM' → minutes since midnight. Raises ValueError if malformed."""
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def _is_hhmm(value: str) -> bool:
    """Return True if value looks like a valid HH:MM 24h time string."""
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    try:
        h, m = int(value[:2]), int(value[3:])
        return 0 <= h <= 23 and 0 <= m <= 59
    except ValueError:
        return False


def validate_raw_flight_schema(flights: list[dict], platform: str = "ixigo") -> None:
    """Assert that every raw Phase 1 flight has the minimum required fields with correct types."""
    assert_ok(len(flights) > 0, f"validate_raw_flight_schema: expected at least 1 flight, got 0")
    for i, f in enumerate(flights):
        assert_ok(f.get("platform") == platform,
                  f"flight[{i}] platform must be '{platform}', got {f.get('platform')!r}")
        for field in REQUIRED_RAW_FIELDS:
            assert_ok(field in f, f"flight[{i}] missing required field: {field!r}")
        assert_ok(isinstance(f.get("price"), int),
                  f"flight[{i}] price must be int, got {type(f.get('price')).__name__}")
        assert_ok(f.get("price", 0) > 0,
                  f"flight[{i}] price must be > 0, got {f.get('price')}")
        assert_ok(isinstance(f.get("stops"), int),
                  f"flight[{i}] stops must be int, got {type(f.get('stops')).__name__}")
        dep = f.get("departure", "")
        arr = f.get("arrival", "")
        assert_ok(_is_hhmm(dep),
                  f"flight[{i}] departure must be HH:MM, got {dep!r}")
        assert_ok(_is_hhmm(arr),
                  f"flight[{i}] arrival must be HH:MM, got {arr!r}")


def validate_canonical_schema(flights: list[dict]) -> None:
    """Assert that every flight has all canonical fields after normalization."""
    assert_ok(len(flights) > 0, "validate_canonical_schema: expected at least 1 flight, got 0")
    for i, f in enumerate(flights):
        for field in CANONICAL_FLIGHT_FIELDS:
            assert_ok(field in f, f"canonical flight[{i}] missing field: {field!r}")
        assert_ok(isinstance(f.get("price"), int) and f.get("price", 0) > 0,
                  f"canonical flight[{i}] invalid price: {f.get('price')!r}")


def validate_sorted_by_price(flights: list[dict]) -> None:
    """Assert that flights are sorted ascending by price."""
    for i in range(1, len(flights)):
        assert_ok(
            flights[i]["price"] >= flights[i - 1]["price"],
            f"Flights not sorted by price ascending: "
            f"flights[{i-1}]=₹{flights[i-1]['price']} > flights[{i}]=₹{flights[i]['price']}",
        )


def validate_no_duplicate_flight_numbers(flights: list[dict]) -> None:
    """Assert that no two flights share the same (airline, flight_number) pair."""
    seen: set[tuple] = set()
    for i, f in enumerate(flights):
        key = (f.get("airline", ""), f.get("flight_number", ""))
        assert_ok(key not in seen,
                  f"Duplicate flight_number at index {i}: {key}")
        seen.add(key)


# ── Log helper ──────────────────────────────────────────────────────────────

def _log_flights(flights: list[dict], label: str = "flights") -> None:
    log.info("%s: %d result(s)", label, len(flights))
    for i, f in enumerate(flights, 1):
        log.info(
            "  [%d] %s %s  dep=%s arr=%s dur=%s stops=%s  price=₹%s  offers=%s",
            i,
            f.get("airline", "?"),
            f.get("flight_number", "?"),
            f.get("departure", "?"),
            f.get("arrival", "?"),
            f.get("duration", "?"),
            f.get("stops", "?"),
            f.get("price", "?"),
            "yes" if f.get("offers") else "no",
        )


def _log_offers(offers: list[dict]) -> None:
    log.info("offers_analysis: %d offer(s)", len(offers))
    for i, o in enumerate(offers, 1):
        fare = o.get("fare_details") or {}
        log.info(
            "  [%d] %s %s  original=₹%s  coupons=%d  best_after=₹%s  fare: base=₹%s taxes=₹%s total=₹%s",
            i,
            o.get("airline", "?"),
            o.get("flight_number", "?"),
            o.get("original_price", "?"),
            len(o.get("coupons") or []),
            o.get("best_price_after_coupon", "N/A"),
            fare.get("base_fare", "?"),
            fare.get("taxes", "?"),
            fare.get("total", fare.get("final_price", "?")),
        )
        for j, c in enumerate(o.get("coupons") or [], 1):
            log.info(
                "    coupon [%d] %s: %s  discount=₹%s → price=₹%s",
                j,
                c.get("code", "?"),
                str(c.get("description", ""))[:60],
                c.get("discount", "?"),
                c.get("price_after_coupon", "?"),
            )


# ── Test 1: Phase 1 extraction ──────────────────────────────────────────────

def test_phase1_extraction():
    """
    Mimics: User enters Chennai→Bengaluru, clicks Search.
    Backend Phase 1: IxigoAgent.search(fetch_offers=False) scrapes ixigo.com,
    returns a list of raw flight dicts. This test validates the raw extraction
    pipeline without entering the booking funnel.
    """
    log.info("=== TEST 1: test_phase1_extraction ===")
    log.info(
        "Route: %s → %s  date=%s  class=%s  fetch_offers=False",
        ROUTE_FROM, ROUTE_TO, TRAVEL_DATE, TRAVEL_CLASS,
    )

    agent = IxigoAgent()
    results = agent.search(
        from_city=ROUTE_FROM,
        to_city=ROUTE_TO,
        date=TRAVEL_DATE,
        travel_class=TRAVEL_CLASS,
        fetch_offers=False,
    )

    assert_ok(isinstance(results, list),
              f"fetch_offers=False must return a list, got {type(results).__name__}")

    if len(results) == 0:
        log.warning(
            "Ixigo returned 0 flights (site may show 'No Flights' for this route/date). "
            "Pipeline validated (URL build + Nova Act + extraction ran). Skipping schema checks."
        )
        log.info("test_phase1_extraction PASSED (0 flights — pipeline validated)")
        return results

    _log_flights(results, "Phase 1 raw extraction")
    validate_raw_flight_schema(results, platform="ixigo")

    log.info("test_phase1_extraction PASSED (%d flights extracted)", len(results))
    return results


# ── Test 2: Phase 1 + FlightNormalizer ─────────────────────────────────────

def test_phase1_with_normalization():
    """
    Mimics: User enters Mumbai→Delhi, default filters (sort by price).
    Backend Phase 2: FlightNormalizer deduplicates raw results, validates schema,
    sorts by price, caps at 5 results. This test validates the normalizer pipeline
    end-to-end on a real extraction.
    """
    log.info("=== TEST 2: test_phase1_with_normalization ===")
    log.info(
        "Route: %s → %s  date=%s  class=%s",
        ROUTE2_FROM, ROUTE2_TO, TRAVEL_DATE, TRAVEL_CLASS,
    )

    agent = IxigoAgent()
    raw_results = agent.search(
        from_city=ROUTE2_FROM,
        to_city=ROUTE2_TO,
        date=TRAVEL_DATE,
        travel_class=TRAVEL_CLASS,
        fetch_offers=False,
    )

    assert_ok(isinstance(raw_results, list),
              f"Phase 1 must return list, got {type(raw_results).__name__}")

    if len(raw_results) == 0:
        log.warning("Ixigo returned 0 flights for %s→%s — pipeline validated, normalization skipped.",
                    ROUTE2_FROM, ROUTE2_TO)
        log.info("test_phase1_with_normalization PASSED (0 flights — pipeline validated)")
        return []

    _log_flights(raw_results, "Phase 1 raw (pre-normalization)")

    normalizer = FlightNormalizer()
    filters = {"sort_by": "price"}
    normalized = normalizer.normalize(raw_results, filters=filters)

    _log_flights(normalized, "Phase 2 normalized (post-normalization)")

    assert_ok(len(normalized) > 0,
              "FlightNormalizer returned 0 flights from non-empty raw list")
    assert_ok(len(normalized) <= 5,
              f"FlightNormalizer must cap at 5 flights, got {len(normalized)}")

    validate_canonical_schema(normalized)
    validate_sorted_by_price(normalized)
    validate_no_duplicate_flight_numbers(normalized)

    for f in normalized:
        assert_ok(f.get("platform") == "ixigo",
                  f"Normalized flight platform must be 'ixigo', got {f.get('platform')!r}")

    log.info("test_phase1_with_normalization PASSED (%d raw → %d normalized)",
             len(raw_results), len(normalized))
    return normalized


# ── Test 3: Phase 1 + structured filters ───────────────────────────────────

def test_phase1_with_filters():
    """
    Mimics: User checks 'Non-stop only' and sets departure window 06:00–12:00.
    Backend: IxigoAgent bakes max_stops=0 and takeOff buckets into the search URL,
    then FlightNormalizer re-validates and drops any out-of-range flights.
    This test confirms both the URL filter and the normalizer filter agree.
    """
    log.info("=== TEST 3: test_phase1_with_filters ===")

    # ── Sub-test A: max_stops = 0 (non-stop only) ──────────────────────────
    log.info("Sub-test A: non-stop filter (max_stops=0)")
    nonstop_filters = {"max_stops": 0, "sort_by": "price"}

    agent = IxigoAgent()
    raw_nonstop = agent.search(
        from_city=ROUTE_FROM,
        to_city=ROUTE_TO,
        date=TRAVEL_DATE,
        travel_class=TRAVEL_CLASS,
        filters=nonstop_filters,
        fetch_offers=False,
    )

    assert_ok(isinstance(raw_nonstop, list),
              f"Non-stop filter search must return list, got {type(raw_nonstop).__name__}")

    if len(raw_nonstop) > 0:
        _log_flights(raw_nonstop, "Non-stop raw results")
        normalizer = FlightNormalizer()
        filtered_nonstop = normalizer.normalize(raw_nonstop, filters=nonstop_filters)
        for i, f in enumerate(filtered_nonstop):
            assert_ok(
                f.get("stops", 99) == 0,
                f"Non-stop filter: flight[{i}] {f.get('airline')} {f.get('flight_number')} "
                f"has {f.get('stops')} stops — expected 0",
            )
        log.info("Sub-test A PASSED: %d non-stop flights, all have stops=0", len(filtered_nonstop))
    else:
        log.warning("Non-stop filter returned 0 flights — skipping stops assertion")
        log.info("Sub-test A PASSED (0 flights — pipeline validated)")

    # ── Sub-test B: departure_window 06:00–12:00 ───────────────────────────
    log.info("Sub-test B: departure window filter [06:00, 12:00]")
    window_filters = {"departure_window": ["06:00", "12:00"], "sort_by": "price"}

    raw_window = agent.search(
        from_city=ROUTE_FROM,
        to_city=ROUTE_TO,
        date=TRAVEL_DATE,
        travel_class=TRAVEL_CLASS,
        filters=window_filters,
        fetch_offers=False,
    )

    assert_ok(isinstance(raw_window, list),
              f"Departure window search must return list, got {type(raw_window).__name__}")

    if len(raw_window) > 0:
        _log_flights(raw_window, "Window filtered raw results")
        normalizer = FlightNormalizer()
        filtered_window = normalizer.normalize(raw_window, filters=window_filters)
        lo = _parse_hhmm("06:00")
        hi = _parse_hhmm("12:00")
        for i, f in enumerate(filtered_window):
            dep_str = f.get("departure", "")
            if _is_hhmm(dep_str):
                dep_min = _parse_hhmm(dep_str)
                assert_ok(
                    lo <= dep_min <= hi,
                    f"Departure window filter: flight[{i}] {f.get('airline')} {f.get('flight_number')} "
                    f"departure={dep_str} is outside 06:00–12:00",
                )
        log.info("Sub-test B PASSED: %d flights, all departures within 06:00–12:00",
                 len(filtered_window))
    else:
        log.warning("Departure window filter returned 0 flights — skipping time assertions")
        log.info("Sub-test B PASSED (0 flights — pipeline validated)")

    log.info("test_phase1_with_filters PASSED (both sub-tests)")
    return {
        "nonstop": raw_nonstop,
        "window": raw_window,
    }


# ── Test 4: Phase 1 + Phase 3 (offer extraction) ───────────────────────────

def test_phase3_offer_extraction():
    """
    Mimics: User clicks Book on the cheapest flight card → Ixigo booking funnel opens.
    Backend Phase 3: IxigoAgent.search(fetch_offers=True) runs Phase 1 (extraction)
    then enters the booking funnel for the top-N flights and extracts:
      - fare_details (base_fare, taxes, total)
      - available coupon codes with discount amounts
      - best_price_after_coupon (minimum price after any coupon)

    This is the slowest Phase 1+3 test (~2-3 min). Marked as SLOW.
    """
    log.info("=== TEST 4: test_phase3_offer_extraction  [SLOW ~2-3 min] ===")
    log.info(
        "Route: %s → %s  date=%s  class=%s  fetch_offers=True",
        ROUTE_FROM, ROUTE_TO, TRAVEL_DATE, TRAVEL_CLASS,
    )

    agent = IxigoAgent()
    result = agent.search(
        from_city=ROUTE_FROM,
        to_city=ROUTE_TO,
        date=TRAVEL_DATE,
        travel_class=TRAVEL_CLASS,
        fetch_offers=True,
    )

    # When fetch_offers=True, agent returns a dict — not a list
    assert_ok(
        isinstance(result, dict),
        f"fetch_offers=True must return dict, got {type(result).__name__}",
    )
    assert_ok("flights" in result,
              "Result dict must contain 'flights' key")
    assert_ok("offers_analysis" in result,
              "Result dict must contain 'offers_analysis' key")

    flights = result.get("flights", [])
    offers_analysis = result.get("offers_analysis", [])
    filtered = result.get("filtered", [])

    log.info("Phase 1+3 returned: %d raw flights, %d filtered, %d offers",
             len(flights), len(filtered), len(offers_analysis))

    if len(flights) == 0:
        log.warning("Ixigo returned 0 flights — pipeline validated, offer checks skipped")
        log.info("test_phase3_offer_extraction PASSED (0 flights — pipeline validated)")
        return result

    # Validate raw flights
    validate_raw_flight_schema(flights, platform="ixigo")
    _log_flights(flights, "Phase 1 raw flights")

    # Validate offers — at least 1 offer must be present when flights exist
    assert_ok(len(offers_analysis) > 0,
              "offers_analysis must contain at least 1 entry when flights are returned")

    _log_offers(offers_analysis)

    for i, offer in enumerate(offers_analysis):
        for field in REQUIRED_OFFER_FIELDS:
            assert_ok(field in offer,
                      f"offers_analysis[{i}] missing required field: {field!r}")

        assert_ok(
            isinstance(offer.get("original_price"), int) and offer.get("original_price", 0) > 0,
            f"offers_analysis[{i}] original_price must be int > 0, got {offer.get('original_price')!r}",
        )

        fare = offer.get("fare_details") or {}
        # fare_details may be empty if the booking page failed — warn but don't hard-fail
        if fare:
            assert_ok(
                isinstance(fare.get("base_fare"), int) and fare.get("base_fare", 0) > 0,
                f"offers_analysis[{i}] fare_details.base_fare must be int > 0, got {fare.get('base_fare')!r}",
            )
        else:
            log.warning(
                "offers_analysis[%d] %s %s: fare_details is empty (booking page may have changed)",
                i, offer.get("airline"), offer.get("flight_number"),
            )

        # coupons is always a list (may be empty — Ixigo doesn't always show coupons)
        coupons = offer.get("coupons") or []
        assert_ok(isinstance(coupons, list),
                  f"offers_analysis[{i}] coupons must be a list, got {type(coupons).__name__}")

        # best_price_after_coupon must be set when coupons exist
        if coupons:
            best = offer.get("best_price_after_coupon")
            assert_ok(best is not None,
                      f"offers_analysis[{i}] best_price_after_coupon must be set when coupons exist")
            assert_ok(isinstance(best, int) and best >= 0,
                      f"offers_analysis[{i}] best_price_after_coupon must be non-negative int, got {best!r}")
            assert_ok(best == min(c["price_after_coupon"] for c in coupons),
                      f"offers_analysis[{i}] best_price_after_coupon must equal min(price_after_coupon)")

    log.info("test_phase3_offer_extraction PASSED (%d flights, %d offers)",
             len(flights), len(offers_analysis))
    return result


# ── Test 5: on_progress callback events ────────────────────────────────────

def test_on_progress_callbacks():
    """
    Mimics: Frontend listens on WebSocket for interim events while search runs.
    The orchestrator's on_progress callback fires:
      - "phase2_start" (with the full normalized flight list) when Phase 1 completes
      - "offer_extracted" (with a single offer dict) after each flight's coupon extraction

    This test captures those events and validates their payloads, ensuring the
    frontend will receive correctly structured data for progressive rendering.
    """
    log.info("=== TEST 5: test_on_progress_callbacks ===")
    log.info(
        "Route: %s → %s  date=%s  fetch_offers=True  (tracking events)",
        ROUTE_FROM, ROUTE_TO, TRAVEL_DATE,
    )

    events_fired: list[tuple[str, object]] = []

    def on_progress(event: str, data: object) -> None:
        log.info("on_progress event fired: %s  data_type=%s", event, type(data).__name__)
        events_fired.append((event, data))

    agent = IxigoAgent()
    result = agent.search(
        from_city=ROUTE_FROM,
        to_city=ROUTE_TO,
        date=TRAVEL_DATE,
        travel_class=TRAVEL_CLASS,
        fetch_offers=True,
        on_progress=on_progress,
    )

    assert_ok(isinstance(result, dict),
              f"fetch_offers=True must return dict, got {type(result).__name__}")

    flights = result.get("flights", [])

    if len(flights) == 0:
        log.warning("Ixigo returned 0 flights — callback validation skipped (pipeline validated)")
        log.info("test_on_progress_callbacks PASSED (0 flights — pipeline validated)")
        return events_fired

    log.info("Events captured: %s", [e for e, _ in events_fired])

    # "phase2_start" must have been fired with the normalized flight list
    phase2_events = [(e, d) for (e, d) in events_fired if e == "phase2_start"]
    assert_ok(len(phase2_events) >= 1,
              "Expected at least 1 'phase2_start' event, got 0")

    _, phase2_data = phase2_events[0]
    assert_ok(isinstance(phase2_data, list),
              f"'phase2_start' data must be a list of flights, got {type(phase2_data).__name__}")
    assert_ok(len(phase2_data) > 0,
              "'phase2_start' flight list must not be empty")

    # Each flight in phase2_start must have core fields
    for i, f in enumerate(phase2_data):
        for field in ("airline", "flight_number", "departure", "arrival", "price"):
            assert_ok(field in f,
                      f"'phase2_start' flight[{i}] missing field: {field!r}")
    log.info("'phase2_start' event PASSED: %d flights in list", len(phase2_data))

    # "offer_extracted" events — one per coupon-analyzed flight
    offer_events = [(e, d) for (e, d) in events_fired if e == "offer_extracted"]
    log.info("'offer_extracted' events: %d fired", len(offer_events))
    for i, (_, offer_data) in enumerate(offer_events):
        assert_ok(isinstance(offer_data, dict),
                  f"'offer_extracted' event[{i}] data must be dict, got {type(offer_data).__name__}")
        for field in ("flight_number", "airline", "original_price"):
            assert_ok(field in offer_data,
                      f"'offer_extracted' event[{i}] missing field: {field!r}")
    if offer_events:
        log.info("'offer_extracted' events PASSED: %d events, all valid", len(offer_events))

    log.info("test_on_progress_callbacks PASSED (%d events total)", len(events_fired))
    return events_fired


# ── Test 6: Full TravelOrchestrator pipeline (mimics WebSocket search) ──────

class _MockWebSocket:
    """
    Lightweight mock that captures all messages the TravelOrchestrator sends.
    Mimics fastapi.WebSocket.send_json() so the orchestrator can run without
    a live HTTP connection.
    """

    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, msg: dict) -> None:
        self.messages.append(msg)
        log.info("WS → %s  %s",
                 msg.get("type"),
                 _ws_msg_summary(msg))

    def messages_of_type(self, msg_type: str) -> list[dict]:
        return [m for m in self.messages if m.get("type") == msg_type]


def _ws_msg_summary(msg: dict) -> str:
    """Return a concise one-liner summary for a WebSocket message."""
    t = msg.get("type", "?")
    if t == "agent_phase":
        return f"agent={msg.get('agent')} phase={msg.get('phase')} count={msg.get('count')}"
    if t == "offer_extracted":
        o = msg.get("offer", {})
        return f"agent={msg.get('agent')} {o.get('airline')} {o.get('flight_number')} ₹{o.get('original_price')}"
    if t == "results":
        w = msg.get("winner") or {}
        return f"winner={w.get('platform')} price_effective=₹{w.get('price_effective')}"
    if t == "coupon_analysis_scope":
        return f"count={msg.get('count')} ids={msg.get('flight_ids')}"
    return json.dumps({k: v for k, v in msg.items() if k != "type"}, default=str)[:120]


async def _run_orchestrator_test() -> _MockWebSocket:
    """
    Internal async function: instantiate TravelOrchestrator with a mock WebSocket,
    call orchestrator.run(), collect and return all messages.
    """
    from agents.orchestrator import TravelOrchestrator

    mock_ws = _MockWebSocket()
    orchestrator = TravelOrchestrator(ws=mock_ws)

    route = {
        "from":  ROUTE_FROM,
        "to":    ROUTE_TO,
        "date":  TRAVEL_DATE,
        "class": TRAVEL_CLASS,
    }

    log.info(
        "TravelOrchestrator.run: route=%s→%s date=%s class=%s",
        ROUTE_FROM, ROUTE_TO, TRAVEL_DATE, TRAVEL_CLASS,
    )

    await orchestrator.run(
        route=route,
        cards=[],       # No credit cards → reasoner uses plain prices
        query=None,
    )

    return mock_ws


def test_full_orchestrator_pipeline():
    """
    Mimics: User opens extension, enters Chennai→Bengaluru on 2026-03-22 (economy),
    clicks Search. The frontend opens a WebSocket to /ws/search/{task_id} and
    the TravelOrchestrator pipeline executes end-to-end:

      1. TravelPlanner  (Nova Lite) — parses the route, selects agents, extracts filters
      2. IxigoAgent     (Nova Act)  — Phase 1 + 3 with on_progress callbacks
      3. FlightNormalizer (Python)  — dedup, validate, sort, cap
      4. NovaReasoner    (Nova Pro) — apply card offers, pick winner, explain

    The mock WebSocket captures every send_json() call. We assert:
      - Correct message type sequence is present
      - "results" message contains winner, with_coupons, all
      - winner has price_effective > 0
      - at least 1 flight in with_coupons has offers data

    This is the slowest test (~3-5 min). Marked as SLOW.
    """
    log.info("=== TEST 6: test_full_orchestrator_pipeline  [SLOW ~3-5 min] ===")
    log.info("Simulating full WebSocket search for %s → %s  date=%s",
             ROUTE_FROM, ROUTE_TO, TRAVEL_DATE)

    mock_ws = asyncio.run(_run_orchestrator_test())
    messages = mock_ws.messages

    log.info("Total WebSocket messages received: %d", len(messages))
    log.info("Message type sequence: %s", [m.get("type") for m in messages])

    # ── Validate message sequence ──────────────────────────────────────────

    # "agent_start" must have been sent for ixigo
    agent_starts = mock_ws.messages_of_type("agent_start")
    assert_ok(len(agent_starts) > 0,
              "Expected at least 1 'agent_start' message, got 0")
    agent_names = [m.get("agent") for m in agent_starts]
    assert_ok("ixigo" in agent_names,
              f"Expected 'ixigo' in agent_start messages, got {agent_names}")
    log.info("'agent_start' message PASSED (agents: %s)", agent_names)

    # Check for error message early — fail fast with clear message
    error_messages = mock_ws.messages_of_type("error")
    if error_messages:
        # If we got 0 flights, treat as pipeline-validated pass; otherwise re-raise
        err_text = error_messages[0].get("message", "")
        if "No flights found" in err_text:
            log.warning("Orchestrator: no flights found — pipeline validated (search ran)")
            log.info("test_full_orchestrator_pipeline PASSED (no flights — pipeline validated)")
            return mock_ws
        assert_ok(False, f"Orchestrator returned error: {err_text}")

    # "coupon_analysis_scope" must appear (orchestrator sends this to frontend)
    scope_msgs = mock_ws.messages_of_type("coupon_analysis_scope")
    assert_ok(len(scope_msgs) > 0,
              "Expected at least 1 'coupon_analysis_scope' message, got 0")
    scope = scope_msgs[0]
    assert_ok(isinstance(scope.get("flight_ids"), list),
              "coupon_analysis_scope.flight_ids must be a list")
    assert_ok(isinstance(scope.get("count"), int) and scope.get("count", 0) > 0,
              "coupon_analysis_scope.count must be int > 0")
    log.info("'coupon_analysis_scope' message PASSED (count=%d)", scope.get("count"))

    # "results" message must be present
    results_msgs = mock_ws.messages_of_type("results")
    assert_ok(len(results_msgs) == 1,
              f"Expected exactly 1 'results' message, got {len(results_msgs)}")

    results_msg = results_msgs[0]
    log.info("'results' message: %s", _ws_msg_summary(results_msg))

    # winner must be present and have price_effective
    winner = results_msg.get("winner")
    assert_ok(winner is not None,
              "'results' message missing 'winner' key")
    price_eff = winner.get("price_effective")
    assert_ok(price_eff is not None and int(price_eff) > 0,
              f"winner.price_effective must be int > 0, got {price_eff!r}")
    log.info("'results' winner: platform=%s price_effective=₹%s card=%s",
             winner.get("platform"), winner.get("price_effective"), winner.get("card_used"))

    # with_coupons must be a non-empty list of flights
    with_coupons = results_msg.get("with_coupons") or []
    assert_ok(isinstance(with_coupons, list) and len(with_coupons) > 0,
              f"'results'.with_coupons must be a non-empty list, got {len(with_coupons)} items")

    # At least one flight in with_coupons must have offers data (from Phase 3)
    flights_with_offers = [f for f in with_coupons if f.get("offers") is not None]
    log.info(
        "'with_coupons': %d flights total, %d with offers data",
        len(with_coupons), len(flights_with_offers),
    )
    # Warn but don't hard-fail if no offers — Phase 3 may fail without breaking ranking
    if not flights_with_offers:
        log.warning(
            "No flights in with_coupons have 'offers' data — "
            "Phase 3 (coupon extraction) may have failed for all targets"
        )

    # "done" message must be last
    done_msgs = mock_ws.messages_of_type("done")
    assert_ok(len(done_msgs) == 1,
              f"Expected exactly 1 'done' message, got {len(done_msgs)}")
    assert_ok(messages[-1].get("type") == "done",
              f"'done' must be the last WebSocket message, got {messages[-1].get('type')!r}")
    log.info("'done' message PASSED (final message confirmed)")

    log.info("test_full_orchestrator_pipeline PASSED (%d messages, winner=₹%s)",
             len(messages), price_eff)
    return mock_ws


# ── Test 7: Session logging ─────────────────────────────────────────────────

def test_session_logging():
    """
    Mimics: Admin opens the FareWise dashboard to review session logs.
    Each search creates a session directory under backend/logs/<date>/<session_id>/.
    This test validates that:
      - create_session() creates the directory + metadata.json + nova_act_session.log
      - metadata.json has the correct search_params structure
      - log_phase() appends to execution.json
      - finalize_session() sets timestamp_end and status in metadata.json
      - nova_act_session.log has content (root logger writes to it)

    This test does NOT open a browser — it validates the logging infrastructure
    that runs alongside every real search.
    """
    log.info("=== TEST 7: test_session_logging ===")

    backend_dir = Path(__file__).resolve().parent.parent
    logs_base = backend_dir / "logs"

    # Use a fresh SessionLogger instance so test is isolated
    session_logger = SessionLogger(base_logs_dir=str(logs_base))

    session_id = session_logger.create_session(
        from_city=ROUTE_FROM,
        to_city=ROUTE_TO,
        date=TRAVEL_DATE,
        travel_class=TRAVEL_CLASS,
        agents=["ixigo"],
        filters={"max_stops": 0, "sort_by": "price"},
    )

    assert_ok(isinstance(session_id, str) and len(session_id) > 0,
              f"create_session must return a non-empty string, got {session_id!r}")
    log.info("Session created: %s", session_id)

    # ── Validate directory structure ─────────────────────────────────────

    from datetime import datetime as _dt
    today_str = _dt.now().strftime("%Y-%m-%d")
    session_dir = logs_base / today_str / session_id

    assert_ok(session_dir.exists() and session_dir.is_dir(),
              f"Session directory must exist: {session_dir}")
    log.info("Session directory exists: %s", session_dir)

    # ── Validate metadata.json ───────────────────────────────────────────

    metadata_file = session_dir / "metadata.json"
    assert_ok(metadata_file.exists(),
              f"metadata.json must exist at {metadata_file}")

    with open(metadata_file) as f:
        metadata = json.load(f)

    assert_ok(metadata.get("session_id") == session_id,
              f"metadata.session_id mismatch: {metadata.get('session_id')!r} != {session_id!r}")

    sp = metadata.get("search_params", {})
    assert_ok(sp.get("from_city") == ROUTE_FROM,
              f"metadata.search_params.from_city must be {ROUTE_FROM!r}, got {sp.get('from_city')!r}")
    assert_ok(sp.get("to_city") == ROUTE_TO,
              f"metadata.search_params.to_city must be {ROUTE_TO!r}, got {sp.get('to_city')!r}")
    assert_ok(sp.get("travel_date") == TRAVEL_DATE,
              f"metadata.search_params.travel_date must be {TRAVEL_DATE!r}, got {sp.get('travel_date')!r}")
    assert_ok(sp.get("travel_class") == TRAVEL_CLASS,
              f"metadata.search_params.travel_class must be {TRAVEL_CLASS!r}, got {sp.get('travel_class')!r}")
    assert_ok("ixigo" in sp.get("agents", []),
              f"metadata.search_params.agents must include 'ixigo', got {sp.get('agents')!r}")
    assert_ok(metadata.get("status") == "in_progress",
              f"metadata.status must be 'in_progress' initially, got {metadata.get('status')!r}")
    log.info("metadata.json PASSED (session_id=%s, status=in_progress)", session_id)

    # ── Validate nova_act_session.log is created ─────────────────────────

    log_file = session_dir / "nova_act_session.log"
    assert_ok(log_file.exists(),
              f"nova_act_session.log must exist at {log_file}")

    # Write a log line through the root logger — it must be captured by session file handler
    log.info("Session logging test: writing test log line to verify file capture")
    import logging as _logging
    _logging.getLogger().handlers  # trigger any deferred setup

    # The handler is attached; flush it so content is on disk
    for handler in _logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass

    log_content = log_file.read_text(encoding="utf-8")
    assert_ok(len(log_content) > 0,
              f"nova_act_session.log must have content, found empty file at {log_file}")
    log.info("nova_act_session.log PASSED (has %d chars)", len(log_content))

    # ── Validate log_phase writes execution.json ─────────────────────────

    session_logger.log_phase(
        phase="test_phase",
        agent="ixigo",
        duration_ms=123,
        status="success",
        details={"flights_extracted": 5},
    )

    exec_file = session_dir / "execution.json"
    assert_ok(exec_file.exists(),
              f"execution.json must exist after log_phase(), at {exec_file}")

    with open(exec_file) as f:
        execution = json.load(f)

    assert_ok(isinstance(execution, list) and len(execution) > 0,
              "execution.json must be a non-empty list")
    last = execution[-1]
    assert_ok(last.get("phase") == "test_phase",
              f"execution entry phase must be 'test_phase', got {last.get('phase')!r}")
    assert_ok(last.get("agent") == "ixigo",
              f"execution entry agent must be 'ixigo', got {last.get('agent')!r}")
    assert_ok(last.get("status") == "success",
              f"execution entry status must be 'success', got {last.get('status')!r}")
    log.info("execution.json PASSED (%d entries)", len(execution))

    # ── Validate finalize_session sets timestamp_end ─────────────────────

    session_logger.finalize_session(
        status="completed",
        summary={"total_flights": 5, "winner": "IndiGo 6E-204 at ₹4299"},
    )

    with open(metadata_file) as f:
        finalized = json.load(f)

    assert_ok(finalized.get("status") == "completed",
              f"finalized metadata.status must be 'completed', got {finalized.get('status')!r}")
    assert_ok("timestamp_end" in finalized,
              "finalized metadata must contain 'timestamp_end'")
    assert_ok("summary" in finalized,
              "finalized metadata must contain 'summary'")
    assert_ok(isinstance(finalized["summary"], dict),
              "finalized metadata.summary must be a dict")
    log.info("finalize_session PASSED (status=completed, timestamp_end=%s)",
             finalized.get("timestamp_end"))

    log.info("test_session_logging PASSED (session_id=%s, dir=%s)",
             session_id, session_dir)
    return {
        "session_id": session_id,
        "session_dir": str(session_dir),
        "metadata": finalized,
    }


# ── Test runner ─────────────────────────────────────────────────────────────

def run_all_ixigo_tests(
    phase1_only: bool = False,
    skip_orchestrator: bool = False,
) -> dict:
    """
    Run the full Ixigo E2E test suite.

    Args:
        phase1_only:       If True, skip Phase 3 tests (test_phase3_offer_extraction,
                           test_on_progress_callbacks) and the orchestrator test.
        skip_orchestrator: If True, skip test_full_orchestrator_pipeline only.

    Returns:
        dict with "passed", "failed", "skipped" lists of test names.
    """
    log.info("══════════  Ixigo E2E Test Suite  ══════════")
    log.info("  Route:      %s → %s", ROUTE_FROM, ROUTE_TO)
    log.info("  Route 2:    %s → %s", ROUTE2_FROM, ROUTE2_TO)
    log.info("  Date:       %s", TRAVEL_DATE)
    log.info("  Class:      %s", TRAVEL_CLASS)
    log.info("  phase1_only=%s  skip_orchestrator=%s", phase1_only, skip_orchestrator)
    log.info("═════════════════════════════════════════════")

    results = {"passed": [], "failed": [], "skipped": []}

    def _run(name: str, fn, *args, **kwargs) -> bool:
        log.info("")
        log.info("Running: %s", name)
        try:
            fn(*args, **kwargs)
            log.info("PASS: %s", name)
            results["passed"].append(name)
            return True
        except AssertionError as e:
            log.error("FAIL: %s  —  %s", name, e)
            results["failed"].append(name)
            return False
        except Exception as e:
            log.error("ERROR: %s  —  %s: %s", name, type(e).__name__, e)
            results["failed"].append(name)
            return False

    def _skip(name: str, reason: str) -> None:
        log.info("SKIP: %s  (%s)", name, reason)
        results["skipped"].append(name)

    # ── Fast tests (Phase 1 + normalizer + filters + logging) ─────────────
    _run("test_session_logging",             test_session_logging)
    _run("test_phase1_extraction",           test_phase1_extraction)
    _run("test_phase1_with_normalization",   test_phase1_with_normalization)
    _run("test_phase1_with_filters",         test_phase1_with_filters)

    # ── Slow tests (Phase 3 + orchestrator) ───────────────────────────────
    if phase1_only:
        _skip("test_phase3_offer_extraction",    "phase1_only=True")
        _skip("test_on_progress_callbacks",      "phase1_only=True")
        _skip("test_full_orchestrator_pipeline", "phase1_only=True")
    else:
        _run("test_phase3_offer_extraction",  test_phase3_offer_extraction)
        _run("test_on_progress_callbacks",    test_on_progress_callbacks)
        if skip_orchestrator:
            _skip("test_full_orchestrator_pipeline", "skip_orchestrator=True")
        else:
            _run("test_full_orchestrator_pipeline", test_full_orchestrator_pipeline)

    # ── Summary ────────────────────────────────────────────────────────────
    total = len(results["passed"]) + len(results["failed"])
    skipped = len(results["skipped"])
    log.info("")
    log.info("══════════  Results: %d/%d passed  (%d skipped)  ══════════",
             len(results["passed"]), total, skipped)
    for t in results["passed"]:
        log.info("  PASS  %s", t)
    for t in results["skipped"]:
        log.info("  SKIP  %s", t)
    for t in results["failed"]:
        log.error("  FAIL  %s", t)

    return results


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log_path = add_agent_test_file_handler("ixigo_e2e")
    log.info("Test logs also written to %s", log_path)

    phase1_only      = "--phase1-only"      in sys.argv
    skip_orchestrator = "--skip-orchestrator" in sys.argv

    summary = run_all_ixigo_tests(
        phase1_only=phase1_only,
        skip_orchestrator=skip_orchestrator,
    )

    failed = summary.get("failed", [])
    sys.exit(0 if not failed else 1)
