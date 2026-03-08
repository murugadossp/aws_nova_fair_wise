"""
Test: Cleartrip — Single Itinerary Flow

Starts from one harvested itinerary URL instead of rerunning search + harvest.
This isolates:
- booking/itinerary fare summary extraction
- coupon extraction
- optional payment probe

Run:
  python3 tests/test_cleartrip_itinerary.py
  CLEARTRIP_ITINERARY_URL="https://..." python3 tests/test_cleartrip_itinerary.py
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from agents.cleartrip.agent import (
    CleartripAgent,
    _CONFIG,
)

log = get_logger(__name__)

_DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "cleartrip_log.txt"
_ITINERARY_URL_RE = re.compile(r"https://www\.cleartrip\.com/flights/itinerary/[^\s\"']+/info")
_HARVEST_LINE_RE = re.compile(
    r"Harvest \[\d+\]: (?P<airline>.+?) (?P<flight_number>[A-Z0-9-]+) → (?P<url>https://www\.cleartrip\.com/flights/itinerary/[^\s\"']+/info)"
)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def _load_latest_harvest_info(log_path: Path) -> dict:
    text = log_path.read_text(encoding="utf-8")
    matches = list(_HARVEST_LINE_RE.finditer(text))
    if matches:
        last = matches[-1]
        return {
            "itinerary_url": last.group("url"),
            "airline": last.group("airline").strip(),
            "flight_number": last.group("flight_number").strip(),
        }

    urls = _ITINERARY_URL_RE.findall(text)
    if urls:
        return {
            "itinerary_url": urls[-1],
            "airline": "UNKNOWN",
            "flight_number": "UNKNOWN",
        }

    raise AssertionError(f"No harvested Cleartrip itinerary URL found in {log_path}")


def _extract_single_itinerary_offer(itinerary_url: str, airline: str, flight_number: str) -> dict:
    workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_CLEARTRIP") or _CONFIG["workflow_name"]
    collect_convenience_fee = bool(_CONFIG.get("collect_convenience_fee", False))
    headless = os.environ.get("FAREWISE_HEADED", "0") != "1"
    return CleartripAgent._extract_offers_from_itinerary_url(
        workflow_name,
        itinerary_url,
        {
            "airline": airline,
            "flight_number": flight_number,
            "price": 0,
        },
        headless,
        collect_convenience_fee,
    )


def validate_single_offer(offer: dict):
    assert_ok(offer.get("additional_urls", {}).get("itinerary", "").startswith("http"), "itinerary URL missing")
    assert_ok(isinstance(offer.get("original_price"), int) and offer["original_price"] > 0, "original_price must be > 0")
    assert_ok(isinstance(offer.get("fare_type"), str), "fare_type must be a string")

    fb = offer.get("fare_breakdown", {})
    for field in ("base_fare", "taxes", "convenience_fee", "total_fare"):
        assert_ok(isinstance(fb.get(field), int), f"fare_breakdown.{field} must be int")
        assert_ok(fb.get(field, -1) >= 0, f"fare_breakdown.{field} must be >= 0")

    for i, coupon in enumerate(offer.get("coupons", [])):
        assert_ok("code" in coupon and coupon["code"], f"coupon[{i}] missing code")
        assert_ok(isinstance(coupon.get("discount"), int) and coupon["discount"] >= 0, f"coupon[{i}] discount invalid")
        expected_after = max(0, offer["original_price"] - coupon["discount"])
        assert_ok(coupon.get("price_after_coupon") == expected_after, f"coupon[{i}] price_after_coupon mismatch")


def test_cleartrip_single_itinerary(itinerary_url: str | None = None) -> dict:
    log_path = Path(os.environ.get("CLEARTRIP_LOG_PATH") or _DEFAULT_LOG_PATH)
    if itinerary_url:
        harvest_info = {
            "itinerary_url": itinerary_url,
            "airline": os.environ.get("CLEARTRIP_ITINERARY_AIRLINE", "UNKNOWN"),
            "flight_number": os.environ.get("CLEARTRIP_ITINERARY_FLIGHT_NUMBER", "UNKNOWN"),
        }
    else:
        harvest_info = _load_latest_harvest_info(log_path)

    log.info(
        "=== test_cleartrip_single_itinerary: %s %s ===",
        harvest_info["airline"],
        harvest_info["flight_number"],
    )
    log.info("Starting from itinerary URL: %s", harvest_info["itinerary_url"])

    offer = _extract_single_itinerary_offer(
        harvest_info["itinerary_url"],
        harvest_info["airline"],
        harvest_info["flight_number"],
    )
    validate_single_offer(offer)

    st = offer["telemetry"]["timings_ms"]
    log.info(
        "Single itinerary telemetry: fare_ms=%s coupon_ms=%s coupon_branch_ms=%s payment_branch_ms=%s wall_clock_ms=%s insurance_ms=%s skip_addons_ms=%s skip_popup_ms=%s contact_ms=%s traveller_ms=%s payment_extract_ms=%s payment_probe_ms=%s total_ms=%s",
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
    )
    log.info(
        "Single itinerary result: original=₹%d fare_type=%s coupons=%d payment_url=%s",
        offer["original_price"],
        offer.get("fare_type") or "—",
        len(offer.get("coupons", [])),
        "yes" if (offer.get("additional_urls", {}) or {}).get("payment") else "no",
    )
    return offer


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("cleartrip_itinerary")
    log.info("Test logs also written to %s", log_path)
    itinerary_url = os.environ.get("CLEARTRIP_ITINERARY_URL")
    result = test_cleartrip_single_itinerary(itinerary_url=itinerary_url)
    log.info("Single itinerary JSON:\n%s", json.dumps(result, indent=2, default=str))
    log.info("Cleartrip single-itinerary test DONE")
