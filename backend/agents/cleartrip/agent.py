"""
Cleartrip — Nova Act Agent

Phase 1 returns candidate flight cards read from the results UI. This output is
useful for observability and debugging, but it is not treated as authoritative
for filtering or offer selection because the model can occasionally over-include
or reconstruct rows while scrolling.

Filtering, sorting, and deduplication happen authoritatively in
FlightNormalizer (Python), not in the Nova Act prompt. Downstream offer
harvesting must use the filtered Python output, not the raw Phase 1 candidate
list directly.

Instructions live in .md files under instructions/; config.yaml holds schemas.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import Callable

import yaml
from nova_act import ActGetResult, ActInvalidModelGenerationError, NovaAct, Workflow

_AGENT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _AGENT_DIR.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from logger import get_logger
from nova_auth import get_or_create_workflow_definition
from agents.act_handler import ActExceptionHandler

log = get_logger(__name__)

with open(_AGENT_DIR / "config.yaml", encoding="utf-8") as _f:
    _CONFIG = yaml.safe_load(_f)


def _sub(s: str, **kwargs: str) -> str:
    """Substitute `{{key}}` placeholders in a template string with provided values."""
    for k, v in kwargs.items():
        s = s.replace(f"{{{{{k}}}}}", v)
    return s


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since `start` from perf_counter()."""
    return int((perf_counter() - start) * 1000)


def _get_instruction(step_cfg: dict) -> str:
    """Instruction text: site_adapter + extractor_prompt (two-layer prompt)."""
    site_file = step_cfg["site_adapter_file"]
    extractor_file = step_cfg["extractor_file"]
    site_path = _AGENT_DIR / site_file
    extractor_path = _AGENT_DIR / extractor_file
    site_content = site_path.read_text(encoding="utf-8").strip()
    extractor_content = extractor_path.read_text(encoding="utf-8").strip()
    return f"{site_content}\n\n{extractor_content}"


def _get_single_instruction(step_cfg: dict) -> str:
    """Read a single instruction file (no site adapter)."""
    path = _AGENT_DIR / step_cfg["instruction_file"]
    return path.read_text(encoding="utf-8").strip()


def _normalize_coupons(coupon_list: list[dict]) -> list[dict]:
    """Fix currency symbol in coupon descriptions.
    Nova Act occasionally returns U+20B5 (₵ Cedi) instead of U+20B9 (₹ Rupee)
    when rendering Indian-locale pages in headless mode. Amounts are always correct.
    """
    for c in coupon_list:
        if "description" in c and isinstance(c["description"], str):
            c["description"] = c["description"].replace("\u20b5", "\u20b9")
    return coupon_list


def _run_coupon_extraction(nova, coupons_cfg: dict, price: int, result: dict) -> None:
    """Run the 'extract_coupons_from_booking_page' act step and populate `result`.

    Reads coupons from the currently open booking/itinerary page, normalises the
    currency symbol (single normalization point for the whole pipeline), computes
    price_after_coupon for each coupon, and stores coupons + best_price_after_coupon
    in `result`. Modifies `result` in place.
    """
    inst = _get_single_instruction(coupons_cfg)
    out = nova.act(inst, max_steps=coupons_cfg.get("max_steps", 12), schema=coupons_cfg.get("schema"))
    coupons = (
        getattr(out, "parsed_response", None)
        if isinstance(out, ActGetResult)
        else (out if isinstance(out, list) else None)
    )
    coupon_list = _normalize_coupons(coupons or [])
    for c in coupon_list:
        c["price_after_coupon"] = max(0, price - c.get("discount", 0))
    result["coupons"] = coupon_list
    if coupon_list:
        result["best_price_after_coupon"] = min(c["price_after_coupon"] for c in coupon_list)


def _parse_act_dict(output) -> dict | None:
    """Return a parsed dict from a Nova act result when available."""
    if isinstance(output, ActGetResult) and isinstance(getattr(output, "parsed_response", None), dict):
        return output.parsed_response
    if isinstance(output, dict):
        return output
    return None


def _run_payment_step(
    nova,
    step_name: str,
    timing_key: str,
    result: dict,
    *,
    optional: bool = False,
):
    """Run one payment-probe step and record its timing."""
    step_cfg = _CONFIG["steps"].get(step_name)
    if not step_cfg:
        return None

    timings = result.setdefault("telemetry", {}).setdefault("timings_ms", {})
    started = perf_counter()
    try:
        output = nova.act(
            _get_single_instruction(step_cfg),
            max_steps=step_cfg.get("max_steps", 10),
            schema=step_cfg.get("schema"),
        )
    except Exception as e:
        timings[timing_key] = _elapsed_ms(started)
        if optional:
            result.setdefault("telemetry", {}).setdefault("payment_probe_step_errors", {})[step_name] = str(e)
            log.debug("Optional payment step failed (%s): %s", step_name, e)
            return None
        raise

    timings[timing_key] = _elapsed_ms(started)
    return _parse_act_dict(output)


def _run_payment_probe(nova, result: dict) -> None:
    """Continue the same Nova session to payment using modular screen-specific acts."""
    timings = result.setdefault("telemetry", {}).setdefault("timings_ms", {})
    probe_started = perf_counter()

    _run_payment_step(
        nova,
        "payment_insurance_continue",
        "insurance_continue_ms",
        result,
        optional=True,
    )
    _run_payment_step(
        nova,
        "payment_skip_addons",
        "skip_addons_ms",
        result,
    )
    _run_payment_step(
        nova,
        "payment_skip_addons_popup",
        "skip_addons_popup_ms",
        result,
        optional=True,
    )
    _run_payment_step(
        nova,
        "payment_contact_continue",
        "contact_continue_ms",
        result,
    )
    _run_payment_step(
        nova,
        "payment_traveller_continue",
        "traveller_continue_ms",
        result,
    )

    parsed = _run_payment_step(
        nova,
        "extract_fare_breakdown",
        "payment_fare_extract_ms",
        result,
    )

    payment_url = nova.page.url
    if payment_url and payment_url.startswith("http"):
        result["additional_urls"]["payment"] = payment_url

    if parsed:
        result["fare_breakdown"] = {
            "base_fare": int(parsed.get("base_fare", 0) or 0),
            "taxes": int(parsed.get("taxes", 0) or 0),
            "convenience_fee": int(parsed.get("convenience_fee", 0) or 0),
            "total_fare": int(parsed.get("total_fare", 0) or 0),
        }

    timings["payment_probe_ms"] = _elapsed_ms(probe_started)


def _new_offer_result(
    workflow_name: str,
    itinerary_url: str,
    flight_info: dict,
    *,
    payment_probe_enabled: bool,
) -> dict:
    return {
        "flight_number": flight_info.get("flight_number", ""),
        "airline": flight_info.get("airline", ""),
        "original_price": int(flight_info.get("price", 0) or 0),
        "fare_type": "VALUE",
        "coupons": [],
        "fare_breakdown": {},
        "best_price_after_coupon": None,
        "additional_urls": {"itinerary": itinerary_url, "payment": ""},
        "telemetry": {
            "workflow_name": workflow_name,
            "model_id": "nova-act-latest",
            "starting_page": itinerary_url,
            "payment_probe_enabled": payment_probe_enabled,
            "timings_ms": {},
        },
    }


def _extract_coupon_offer_branch(
    workflow_name: str,
    itinerary_url: str,
    flight_info: dict,
    headless: bool,
) -> dict:
    airline = flight_info.get("airline", "")
    flight_number = flight_info.get("flight_number", "")
    price = int(flight_info.get("price", 0) or 0)
    session_started = perf_counter()
    result = _new_offer_result(
        workflow_name,
        itinerary_url,
        flight_info,
        payment_probe_enabled=False,
    )
    timings = result["telemetry"]["timings_ms"]
    try:
        get_or_create_workflow_definition(workflow_name)
        with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
            with NovaAct(workflow=wf, starting_page=itinerary_url, headless=headless, tty=False, ignore_https_errors=True) as nova:
                booking_fare_cfg = _CONFIG["steps"].get("extract_fare_summary_booking")
                if booking_fare_cfg:
                    try:
                        fare_started = perf_counter()
                        out = nova.act(
                            _get_single_instruction(booking_fare_cfg),
                            max_steps=booking_fare_cfg.get("max_steps", 12),
                            schema=booking_fare_cfg.get("schema"),
                        )
                        parsed = _parse_act_dict(out)
                        if parsed:
                            base_fare_raw = parsed.get("base_fare")
                            taxes_raw = parsed.get("taxes")
                            if parsed.get("fare_type"):
                                result["fare_type"] = str(parsed["fare_type"]).strip().upper() or result["fare_type"]
                            if base_fare_raw is not None and taxes_raw is not None:
                                base_fare = int(base_fare_raw)
                                taxes = int(taxes_raw)
                                conv = int(parsed.get("convenience_fee", 0) or 0)
                                total = int(parsed.get("total_fare", 0) or 0)
                                if total == 0:
                                    total = price
                                if conv == 0 and total >= base_fare + taxes:
                                    conv = total - base_fare - taxes
                                result["fare_breakdown"] = {
                                    "base_fare": base_fare,
                                    "taxes": taxes,
                                    "convenience_fee": conv,
                                    "total_fare": total,
                                }
                                result["original_price"] = total
                        timings["fare_summary_ms"] = _elapsed_ms(fare_started)
                    except Exception as e:
                        log.debug("Fare summary extraction failed for %s %s: %s", airline, flight_number, e)
                coupons_cfg = _CONFIG["steps"].get("extract_coupons_from_booking_page")
                if coupons_cfg:
                    coupon_started = perf_counter()
                    _run_coupon_extraction(nova, coupons_cfg, result["original_price"] or price, result)
                    timings["coupon_ms"] = _elapsed_ms(coupon_started)
    except Exception as e:
        log.warning("Coupon branch failed for %s %s: %s", airline, flight_number, e)
        result["error"] = str(e)
    timings["coupon_branch_total_ms"] = _elapsed_ms(session_started)
    return result


def _extract_payment_offer_branch(
    workflow_name: str,
    itinerary_url: str,
    flight_info: dict,
    headless: bool,
) -> dict:
    airline = flight_info.get("airline", "")
    flight_number = flight_info.get("flight_number", "")
    session_started = perf_counter()
    result = _new_offer_result(
        workflow_name,
        itinerary_url,
        flight_info,
        payment_probe_enabled=True,
    )
    timings = result["telemetry"]["timings_ms"]
    try:
        get_or_create_workflow_definition(workflow_name)
        with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
            with NovaAct(workflow=wf, starting_page=itinerary_url, headless=headless, tty=False, ignore_https_errors=True) as nova:
                _run_payment_probe(nova, result)
    except Exception as e:
        log.warning("Payment probe failed for %s %s: %s", airline, flight_number, e)
        result["telemetry"]["payment_probe_error"] = str(e)
    timings["payment_probe_branch_total_ms"] = _elapsed_ms(session_started)
    return result


def _merge_offer_branch_results(coupon_result: dict, payment_result: dict | None = None) -> dict:
    merge_started = perf_counter()
    merged = coupon_result
    merged_telemetry = merged.setdefault("telemetry", {})
    merged_timings = merged_telemetry.setdefault("timings_ms", {})

    if payment_result:
        payment_telemetry = payment_result.get("telemetry") or {}
        payment_timings = payment_telemetry.get("timings_ms") or {}
        for key, value in payment_timings.items():
            if key != "session_total_ms":
                merged_timings[key] = value
        payment_url = ((payment_result.get("additional_urls") or {}).get("payment") or "").strip()
        if payment_url:
            merged.setdefault("additional_urls", {})["payment"] = payment_url
        if payment_result.get("fare_breakdown"):
            merged["fare_breakdown"] = payment_result["fare_breakdown"]
        if payment_telemetry.get("payment_probe_error"):
            merged_telemetry["payment_probe_error"] = payment_telemetry["payment_probe_error"]
        if payment_telemetry.get("payment_probe_step_errors"):
            merged_telemetry["payment_probe_step_errors"] = payment_telemetry["payment_probe_step_errors"]
        merged_telemetry["payment_probe_enabled"] = True

    merged_timings["offer_merge_ms"] = _elapsed_ms(merge_started)
    return merged


def _dedup_raw_items(items: list[dict]) -> list[dict]:
    """Remove exact duplicate Phase 1 rows from candidate extraction output.

    The Nova Act model occasionally returns the same card more than once during a
    scroll-through. Deduplicate by a fuller card identity instead of flight_number
    alone so we do not accidentally collapse legitimate distinct rows that happen
    to reuse a flight number.
    """
    seen: set[tuple[str, str, str, str, int | str]] = set()
    deduped: list[dict] = []
    for item in items:
        key = (
            str(item.get("airline", "")).strip(),
            str(item.get("flight_number", "")).strip(),
            str(item.get("departure", "")).strip(),
            str(item.get("arrival", "")).strip(),
            item.get("price", ""),
        )
        if key in seen:
            log.warning(
                "Phase 1: duplicate candidate row dropped (hallucination guard) — "
                "airline=%s flight_number=%s departure=%s arrival=%s price=%s",
                item.get("airline"), item.get("flight_number"), item.get("departure"),
                item.get("arrival"), item.get("price"),
            )
        else:
            seen.add(key)
            deduped.append(item)
    return deduped


def _build_results(items: list[dict], search_url: str, from_city: str, to_city: str, date: str, travel_class: str) -> list[dict]:
    """Convert Phase 1 candidate items into result dicts with the search page URL."""
    results = []
    for item in items:
        results.append({
            "platform": "cleartrip",
            "from_city": from_city,
            "to_city": to_city,
            "date": date,
            "class": travel_class,
            **item,
            "url": search_url,
        })
    return results


def _hhmm_to_minutes(t: str) -> int:
    """Parse an HH:MM string and return total minutes since midnight."""
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def _load_time_buckets() -> list[tuple[str, int, int]]:
    """Read time_buckets from config.yaml → [(label, start_min, end_min), ...]."""
    raw = _CONFIG.get("time_buckets") or []
    buckets = []
    for b in raw:
        buckets.append((
            b["label"],
            _hhmm_to_minutes(b["start"]),
            _hhmm_to_minutes(b["end"]),
        ))
    return buckets


def _build_search_url(
    base_url: str,
    from_code: str,
    to_code: str,
    date_ct: str,
    travel_class: str = "economy",
    filters: dict | None = None,
) -> str:
    """Build Cleartrip results URL, encoding stops and class as query params.

    Note: Cleartrip's consumer results page does not expose a departure time-of-day
    (e.g. Morning / Evening) filter in the URL. Only from, to, depart_date, class,
    stops, etc. are supported. Time-window filtering is done via the TIMINGS
    checkboxes in the UI (see extract_with_filter / _departure_window_to_checkboxes).
    """
    class_codes = _CONFIG.get("class_codes") or {}
    cls = class_codes.get(travel_class.lower().strip(), "Economy")

    url = (
        f"{base_url}/flights/results?"
        f"from={from_code}&to={to_code}&depart_date={date_ct}"
        f"&adults=1&childs=0&infants=0&class={cls}&intl=n&sd=1"
    )

    if filters:
        max_stops = filters.get("max_stops")
        if max_stops is not None:
            url += f"&stops={int(max_stops)}"

    return url


def _departure_window_to_checkboxes(window: list[str] | None) -> list[str]:
    """Map a departure_window ["HH:MM", "HH:MM"] to Cleartrip TIMINGS checkbox labels.

    Selects every bucket that overlaps with the inclusive [lo, hi] window.
    Returns [] if no window or window covers all buckets (no pre-filter needed).
    """
    if not window or len(window) != 2:
        return []
    try:
        lo = _hhmm_to_minutes(window[0])
        hi = _hhmm_to_minutes(window[1])
    except (ValueError, AttributeError):
        return []
    buckets = _load_time_buckets()
    if not buckets:
        return []
    labels = [label for label, bstart, bend in buckets if lo < bend and bstart <= hi]
    if len(labels) == len(buckets):
        return []
    return labels


def _timing_instruction(section: str, city: str, checkboxes: list[str], disabled_behavior: str) -> str:
    """Build a concrete timing-filter instruction line for the prompt."""
    if checkboxes:
        joined = ", ".join(f'"{cb}"' for cb in checkboxes)
        return f'- **{section}:** Under "{section} {city}" in the TIMINGS section, click these checkboxes: {joined}'
    return disabled_behavior


def _bucket_label_for_time(hhmm: str) -> str | None:
    """Return the configured Cleartrip timing bucket label for an HH:MM string."""
    try:
        value = _hhmm_to_minutes(hhmm)
    except (ValueError, AttributeError, TypeError):
        return None
    for label, start_min, end_min in _load_time_buckets():
        if start_min <= value < end_min:
            return label
    return None


def _log_phase1_candidate_warnings(
    items: list[dict],
    departure_checkboxes: list[str],
    arrival_checkboxes: list[str],
) -> None:
    """Log suspicious Phase 1 rows without changing response shape or flow."""
    if not items:
        return
    for item in items:
        if departure_checkboxes:
            dep_label = _bucket_label_for_time(item.get("departure", ""))
            if dep_label is None:
                log.warning(
                    "Phase 1: candidate row has unreadable departure time — flight=%s %s departure=%r",
                    item.get("airline"), item.get("flight_number"), item.get("departure"),
                )
            elif dep_label not in departure_checkboxes:
                log.warning(
                    "Phase 1: candidate row falls outside selected departure buckets — "
                    "flight=%s %s departure=%s bucket=%s selected=%s",
                    item.get("airline"), item.get("flight_number"), item.get("departure"),
                    dep_label, departure_checkboxes,
                )
        if arrival_checkboxes:
            arr_label = _bucket_label_for_time(item.get("arrival", ""))
            if arr_label is None:
                log.warning(
                    "Phase 1: candidate row has unreadable arrival time — flight=%s %s arrival=%r",
                    item.get("airline"), item.get("flight_number"), item.get("arrival"),
                )
            elif arr_label not in arrival_checkboxes:
                log.warning(
                    "Phase 1: candidate row falls outside selected arrival buckets — "
                    "flight=%s %s arrival=%s bucket=%s selected=%s",
                    item.get("airline"), item.get("flight_number"), item.get("arrival"),
                    arr_label, arrival_checkboxes,
                )


class CleartripAgent:

    def _get_code(self, city: str) -> str:
        """Map a city name to its IATA airport code using config.yaml city_codes."""
        codes = _CONFIG.get("city_codes") or {}
        return codes.get(city.lower().strip(), city.upper()[:3])

    @staticmethod
    def _filters_to_criteria(filters: dict | None) -> str:
        """No filtering in Nova Act — FlightNormalizer handles it in Python."""
        return "all available flights"

    @staticmethod
    def _filter_items_for_offers(items: list[dict], filters: dict | None) -> list[dict]:
        """Apply departure_window, arrival_window, and max_stops to raw items so offers use filtered list."""
        if not filters:
            return items
        result = items
        max_stops = filters.get("max_stops")
        if max_stops is not None:
            result = [f for f in result if f.get("stops", 99) <= max_stops]
        window = filters.get("departure_window")
        if window and len(window) == 2:
            try:
                lo = _hhmm_to_minutes(window[0])
                hi = _hhmm_to_minutes(window[1])
            except (ValueError, AttributeError, TypeError):
                pass
            else:
                filtered = []
                for f in result:
                    try:
                        dep = _hhmm_to_minutes(f.get("departure", "00:00"))
                        if lo <= dep <= hi:
                            filtered.append(f)
                    except (ValueError, AttributeError, TypeError):
                        continue
                if filtered:
                    result = filtered
        arr_window = filters.get("arrival_window")
        if arr_window and len(arr_window) == 2:
            try:
                lo = _hhmm_to_minutes(arr_window[0])
                hi = _hhmm_to_minutes(arr_window[1])
            except (ValueError, AttributeError, TypeError):
                pass
            else:
                filtered = []
                for f in result:
                    try:
                        arr = _hhmm_to_minutes(f.get("arrival", "00:00"))
                        if lo <= arr <= hi:
                            filtered.append(f)
                    except (ValueError, AttributeError, TypeError):
                        continue
                if filtered:
                    result = filtered
        return result

    @staticmethod
    def _apply_convenience_fee_from_first(offers_analysis: list[dict]) -> None:
        """Use convenience_fee from the first offer that has it; apply only that value to others.
        Do not use base_fare/taxes/total_fare from index 0 — each offer keeps its own fare; we only reuse convenience_fee.
        When an offer has empty fare_breakdown (e.g. parallel session hit max_steps), fill a minimal breakdown with
        convenience_fee and total_fare from original_price so the offer still shows a breakdown."""
        if not _CONFIG.get("reuse_probe_convenience_fee", True):
            return
        if not offers_analysis:
            return
        conv = None
        for offer in offers_analysis:
            fb = offer.get("fare_breakdown") or {}
            c = fb.get("convenience_fee")
            if c is not None and isinstance(c, (int, float)) and c >= 0:
                conv = c
                break
        if conv is None:
            return
        for i in range(len(offers_analysis)):
            fb = offers_analysis[i].get("fare_breakdown") or {}
            price = int(offers_analysis[i].get("original_price") or 0)
            if fb:
                base = fb.get("base_fare")
                taxes = fb.get("taxes")
                if base is not None and taxes is not None:
                    offers_analysis[i]["fare_breakdown"] = {**fb, "convenience_fee": conv}
                    try:
                        total = int(base) + int(taxes) + int(conv)
                        offers_analysis[i]["fare_breakdown"]["total_fare"] = total
                    except (TypeError, ValueError):
                        pass
            elif conv is not None and price > 0:
                # Offer had empty fare_breakdown (e.g. extract_fare_summary_booking failed); still apply convenience_fee
                try:
                    base = max(0, price - int(conv))
                    offers_analysis[i]["fare_breakdown"] = {
                        "base_fare": base,
                        "taxes": 0,
                        "convenience_fee": conv,
                        "total_fare": price,
                        "source": "fallback",
                    }
                except (TypeError, ValueError):
                    pass

    @staticmethod
    def _harvest_itinerary_urls(
        nova,
        items: list[dict],
        search_url: str,
        on_url_harvested: Callable[[int, dict, str], None] | None = None,
    ) -> list[dict]:
        """Phase A: For each of top N flights, Book → Continue to itinerary only → capture URL.
        Returns list of {flight, itinerary_url}. No extraction in main session.
        If on_url_harvested is set, calls it with (harvest_index, flight, itinerary_url) for each captured URL."""
        top_n = _CONFIG.get("offers_top_n", 3)
        sorted_by_price = sorted(items, key=lambda x: x.get("price", float("inf")))
        targets = sorted_by_price[:top_n]
        harvested: list[dict] = []
        combined_cfg = _CONFIG["steps"].get("book_then_continue")
        if not combined_cfg:
            log.warning("book_then_continue step missing; cannot harvest URLs")
            return harvested
        for idx, flight in enumerate(targets):
            airline = flight["airline"]
            flight_number = flight["flight_number"]
            price = flight["price"]
            log.info("Harvest [%d/%d]: %s %s ₹%d", idx + 1, len(targets), airline, flight_number, price)
            harvest_started = perf_counter()
            try:
                if idx > 0:
                    nova.page.goto(search_url)
                    nova.page.wait_for_load_state("domcontentloaded")
                combined_instruction = _sub(
                    _get_single_instruction(combined_cfg),
                    airline=airline,
                    flight_number=flight_number,
                    price=str(price),
                )
                nova.act(combined_instruction, max_steps=combined_cfg.get("max_steps", 8))
                try:
                    nova.page.wait_for_url("**/flights/itinerary/**/info", timeout=8000)
                except Exception:
                    pass
                itinerary_url = nova.page.url
                if itinerary_url and itinerary_url.startswith("http"):
                    harvested.append({
                        "flight": flight,
                        "itinerary_url": itinerary_url,
                        "telemetry": {
                            "flight_number": flight_number,
                            "airline": airline,
                            "harvest_ms": _elapsed_ms(harvest_started),
                            "itinerary_url": itinerary_url,
                        },
                    })
                    log.info("Harvest [%d/%d]: %s %s → %s", idx + 1, len(targets), airline, flight_number, itinerary_url[:60])
                    if on_url_harvested:
                        on_url_harvested(idx, flight, itinerary_url)
                else:
                    log.warning("Harvest [%d/%d]: invalid URL for %s %s", idx + 1, len(targets), airline, flight_number)
            except Exception as e:
                log.warning("Harvest [%d/%d]: failed for %s %s: %s", idx + 1, len(targets), airline, flight_number, e)
        return harvested

    @staticmethod
    def _extract_offers_from_itinerary_url(
        workflow_name: str,
        itinerary_url: str,
        flight_info: dict,
        headless: bool,
        do_payment_probe: bool = False,
    ) -> dict:
        """Open itinerary_url in fresh Nova sessions and merge branch results.

        Coupon extraction stays on the itinerary page. When payment probing is enabled,
        a second independent session starts from the same itinerary URL in parallel so
        coupon-dialog state cannot leak into the convenience-fee flow.
        """
        session_started = perf_counter()
        if not do_payment_probe:
            result = _extract_coupon_offer_branch(workflow_name, itinerary_url, flight_info, headless)
            result.setdefault("telemetry", {}).setdefault("timings_ms", {})["session_total_ms"] = _elapsed_ms(session_started)
            return result

        parallel_started = perf_counter()
        with ThreadPoolExecutor(max_workers=2) as executor:
            coupon_future = executor.submit(
                _extract_coupon_offer_branch,
                workflow_name,
                itinerary_url,
                flight_info,
                headless,
            )
            payment_future = executor.submit(
                _extract_payment_offer_branch,
                workflow_name,
                itinerary_url,
                flight_info,
                headless,
            )
            coupon_result = coupon_future.result()
            payment_result = payment_future.result()

        merged = _merge_offer_branch_results(coupon_result, payment_result)
        merged.setdefault("telemetry", {}).setdefault("timings_ms", {})["parallel_branch_wall_clock_ms"] = _elapsed_ms(parallel_started)
        merged["telemetry"]["timings_ms"]["session_total_ms"] = _elapsed_ms(session_started)
        return merged

    def search(
        self,
        from_city: str,
        to_city: str,
        date: str,
        travel_class: str = "economy",
        filters: dict | None = None,
        fetch_offers: bool = False,
    ) -> list[dict] | dict:
        """Extract ALL flights, then optionally check offers in the same session."""
        log.info("Searching Cleartrip: %s→%s date=%s class=%s fetch_offers=%s", from_city, to_city, date, travel_class, fetch_offers)
        search_started = perf_counter()

        # ── Phase 1: Resolve city codes, build search URL, open Nova Act browser session ──────────
        os.environ.pop("NOVA_ACT_API_KEY", None)

        workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_CLEARTRIP") or _CONFIG["workflow_name"]
        base_url = _CONFIG["base_url"]
        from_code = self._get_code(from_city)
        to_code = self._get_code(to_city)
        date_ct = self._format_date(date)

        url = _build_search_url(base_url, from_code, to_code, date_ct, travel_class, filters)
        telemetry = {
            "workflow_name": workflow_name,
            "model_id": "nova-act-latest",
            "search_url": url,
            "collect_convenience_fee": _CONFIG.get("collect_convenience_fee", False),
            "convenience_fee_probe_index": int(_CONFIG.get("convenience_fee_probe_index", 0) or 0),
            "timings_ms": {},
            "harvest": [],
            "offer_sessions": [],
        }

        get_or_create_workflow_definition(workflow_name)

        headless = os.environ.get("FAREWISE_HEADED", "0") != "1"
        context = {"from": from_city, "to": to_city, "date": date}
        try:
            results: list[dict] = []
            max_steps = int(os.environ.get("NOVA_ACT_MAX_STEPS", _CONFIG.get("max_steps_default", 50)))
            criteria = self._filters_to_criteria(filters)

            with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
                with NovaAct(workflow=wf, starting_page=url, headless=headless, tty=False, ignore_https_errors=True) as nova:
                    log.debug("Nova Act browser started for cleartrip.com (workflow=%s)", workflow_name)

                    # ── Phase 2: Extract flights from results page ─────────────────────────────────────
                    # Tries a single combined act (filter + extract). Falls back to two-act approach
                    # (pre-filter act, then extraction act) if the combined act fails.
                    dep_checkboxes = _departure_window_to_checkboxes(
                        (filters or {}).get("departure_window"),
                    )
                    arr_checkboxes = _departure_window_to_checkboxes(
                        (filters or {}).get("arrival_window"),
                    )
                    has_time_filter = bool(dep_checkboxes or arr_checkboxes)
                    extraction_cfg = _CONFIG["steps"]["extraction"]
                    extraction_schema = extraction_cfg["schema"]
                    extracted = None

                    if has_time_filter and _CONFIG["steps"].get("extract_with_filter"):
                        combined_cfg = _CONFIG["steps"]["extract_with_filter"]
                        departure_instruction = _timing_instruction(
                            "Taking off from",
                            from_city,
                            dep_checkboxes,
                            "- **Departure:** No departure timing checkboxes were requested for this run. Do not interact with any departure timing filters.",
                        )
                        arrival_instruction = _timing_instruction(
                            "Landing in",
                            to_city,
                            arr_checkboxes,
                            "- **Arrival:** Arrival filtering is disabled for this run. Do NOT scroll the left sidebar again. Do NOT look for, inspect, mention, or interact with the arrival timing section. Go straight to PHASE 2 after applying the departure checkboxes.",
                        )
                        combined_instruction = _sub(
                            _get_instruction(combined_cfg),
                            from_city=from_city,
                            to_city=to_city,
                            departure_instruction=departure_instruction,
                            arrival_instruction=arrival_instruction,
                        )
                        log.info("Combined filter+extract: departure=%s arrival=%s (single act)", dep_checkboxes, arr_checkboxes)
                        try:
                            phase1_started = perf_counter()
                            extracted = nova.act(
                                combined_instruction,
                                max_steps=max_steps,
                                schema=extraction_schema,
                            )
                            telemetry["timings_ms"]["phase1_extract_ms"] = _elapsed_ms(phase1_started)
                        except Exception as combined_err:
                            log.warning("Combined filter+extract failed (%s), falling back to two-act approach", combined_err)
                            extracted = None

                    if extracted is None:
                        if has_time_filter and extracted is None:
                            prefilter_cfg = _CONFIG["steps"].get("pre_filter")
                            if prefilter_cfg:
                                pf_path = _AGENT_DIR / prefilter_cfg["instruction_file"]
                                pf_instruction = _sub(
                                    pf_path.read_text(encoding="utf-8").strip(),
                                    from_city=from_city,
                                    to_city=to_city,
                                    departure_checkboxes=", ".join(f'"{cb}"' for cb in dep_checkboxes) if dep_checkboxes else "—",
                                    arrival_checkboxes=", ".join(f'"{cb}"' for cb in arr_checkboxes) if arr_checkboxes else "—",
                                )
                                pf_max_steps = prefilter_cfg.get("max_steps", 10)
                                log.info("Fallback pre-filter: departure=%s arrival=%s", dep_checkboxes, arr_checkboxes)
                                try:
                                    nova.act(pf_instruction, max_steps=pf_max_steps)
                                except Exception as pf_err:
                                    log.warning("Fallback pre-filter failed (%s), extracting unfiltered", pf_err)

                        extraction_instruction = _sub(
                            _get_instruction(extraction_cfg),
                            criteria=criteria,
                        )
                        phase1_started = perf_counter()
                        extracted = nova.act(
                            extraction_instruction,
                            max_steps=max_steps,
                            schema=extraction_schema,
                        )
                        telemetry["timings_ms"]["phase1_extract_ms"] = _elapsed_ms(phase1_started)

                    items = None
                    if isinstance(extracted, ActGetResult) and isinstance(getattr(extracted, "parsed_response", None), list):
                        items = extracted.parsed_response
                    elif isinstance(extracted, list):
                        items = extracted

                    if items is not None:
                        # Phase 1 output is a candidate list from the UI. Keep it for visibility,
                        # but do not treat it as the authoritative filtered set.
                        items = _dedup_raw_items(items)
                        _log_phase1_candidate_warnings(items, dep_checkboxes, arr_checkboxes)
                        results = _build_results(items, url, from_city, to_city, date, travel_class)
                        log.info("Cleartrip returned %d flights for %s→%s on %s", len(results), from_city, to_city, date)

                        # ── Phase 3: Filter candidates for offer harvesting ───────────────────────────────
                        if results and fetch_offers:
                            try:
                                filtered_items = self._filter_items_for_offers(items, filters)
                                use_parallel = _CONFIG.get("use_parallel_offers", False)
                                max_parallel = _CONFIG.get("max_parallel_offers", 2)
                                collect_convenience_fee = _CONFIG.get("collect_convenience_fee", False)
                                convenience_fee_probe_index = int(_CONFIG.get("convenience_fee_probe_index", 0) or 0)
                                if use_parallel and filtered_items:
                                    top_n = min(_CONFIG.get("offers_top_n", 3), len(filtered_items))
                                    max_workers = min(max_parallel, top_n)
                                    # ── Phase 4: Harvest itinerary URLs sequentially ─────────────────────────────────
                                    # Click Book on each target flight to land on its itinerary page and capture the
                                    # URL. All URLs are collected before any parallel work begins so both sessions
                                    # can start at the same time.
                                    harvest_started = perf_counter()
                                    harvested = self._harvest_itinerary_urls(
                                        nova,
                                        filtered_items,
                                        url,
                                        on_url_harvested=None,
                                    )
                                    telemetry["timings_ms"]["harvest_total_ms"] = _elapsed_ms(harvest_started)
                                    telemetry["harvest"] = [h.get("telemetry", {}) for h in harvested]
                                    log.info("Harvest complete: %d/%d URLs captured", len(harvested), top_n)
                                    for h_idx, h in enumerate(harvested):
                                        log.info("  Harvest [%d]: %s %s → %s",
                                                 h_idx + 1, h["flight"]["airline"],
                                                 h["flight"]["flight_number"],
                                                 h.get("itinerary_url", "NONE"))
                                    # ── Phase 5: Extract offers in parallel (one Nova session per flight URL) ────────
                                    # Each session: fare summary first (page is clean), then coupons.
                                    # convenience_fee is propagated from the first offer to all others afterward.
                                    offers_analysis = []
                                    if harvested:
                                        headless = os.environ.get("NOVA_ACT_HEADLESS", "true").lower() == "true"
                                        parallel_started = perf_counter()
                                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                                            futures = {
                                                executor.submit(
                                                    self._extract_offers_from_itinerary_url,
                                                    workflow_name,
                                                    h["itinerary_url"],
                                                    h["flight"],
                                                    headless,
                                                    collect_convenience_fee and idx == convenience_fee_probe_index,
                                                ): h
                                                for idx, h in enumerate(harvested)
                                            }
                                            for future in as_completed(futures):
                                                h = futures[future]
                                                try:
                                                    offer = future.result()
                                                    offers_analysis.append(offer)
                                                except Exception as e:
                                                    log.warning("Parallel coupons failed for %s %s: %s",
                                                                h["flight"].get("airline"), h["flight"].get("flight_number"), e)
                                                    fl = h["flight"]
                                                    offers_analysis.append({
                                                        "flight_number": fl["flight_number"],
                                                        "airline": fl["airline"],
                                                        "original_price": fl.get("price", 0),
                                                        "fare_type": "VALUE",
                                                        "coupons": [],
                                                        "fare_breakdown": {},
                                                        "best_price_after_coupon": None,
                                                        "additional_urls": {"itinerary": h.get("itinerary_url", ""), "payment": ""},
                                                        "telemetry": {
                                                            "workflow_name": workflow_name,
                                                            "model_id": "nova-act-latest",
                                                            "starting_page": h.get("itinerary_url", ""),
                                                            "timings_ms": {},
                                                        },
                                                        "error": str(e),
                                                    })
                                        telemetry["timings_ms"]["offer_parallel_wall_clock_ms"] = _elapsed_ms(parallel_started)
                                        # Preserve order by harvested (flight 1, flight 2)
                                        key = lambda o: (o.get("airline"), o.get("flight_number"))
                                        harvested_keys = [(h["flight"]["airline"], h["flight"]["flight_number"]) for h in harvested]
                                        offers_analysis.sort(key=lambda o: harvested_keys.index(key(o)) if key(o) in harvested_keys else 999)
                                        telemetry["offer_sessions"] = [
                                            {
                                                "flight_number": offer.get("flight_number"),
                                                "airline": offer.get("airline"),
                                                "starting_page": (offer.get("telemetry") or {}).get("starting_page", ""),
                                                "payment_probe_enabled": (offer.get("telemetry") or {}).get("payment_probe_enabled", False),
                                                "payment_probe_error": (offer.get("telemetry") or {}).get("payment_probe_error", ""),
                                                "timings_ms": (offer.get("telemetry") or {}).get("timings_ms", {}),
                                            }
                                            for offer in offers_analysis
                                        ]
                                self._apply_convenience_fee_from_first(offers_analysis)
                                telemetry["timings_ms"]["total_search_ms"] = _elapsed_ms(search_started)
                                log.info(
                                    "Cleartrip telemetry: total=%dms phase1=%dms harvest=%dms parallel=%dms",
                                    telemetry["timings_ms"].get("total_search_ms", 0),
                                    telemetry["timings_ms"].get("phase1_extract_ms", 0),
                                    telemetry["timings_ms"].get("harvest_total_ms", 0),
                                    telemetry["timings_ms"].get("offer_parallel_wall_clock_ms", 0),
                                )
                                return {
                                    "telemetry": telemetry,
                                    "flights": results,
                                    "offers_analysis": offers_analysis,
                                }
                            except Exception as off_e:
                                log.warning("Cleartrip offers step failed, returning flights only: %s", off_e)
                    else:
                        log.warning("Cleartrip extraction returned unexpected type: %s", type(extracted))
            return results
        except Exception as e:
            # If the SDK rejected the response but the model returned valid JSON, try to recover
            if isinstance(e, ActInvalidModelGenerationError):
                raw = getattr(e, "raw_response", None)
                if isinstance(raw, str):
                    raw = raw.strip()
                    if raw:
                        try:
                            data = json.loads(raw)
                            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "airline" in data[0]:
                                results = _build_results(data, url, from_city, to_city, date, travel_class)
                                log.info(
                                    "Cleartrip: recovered %d flights from raw_response after ActInvalidModelGenerationError",
                                    len(results),
                                )
                                return results
                        except (json.JSONDecodeError, KeyError, TypeError):
                            pass
            return ActExceptionHandler.handle(e, "Cleartrip", context)

    def _format_date(self, date_str: str) -> str:
        """Convert YYYY-MM-DD to DD/MM/YYYY (Cleartrip search URL date format)."""
        try:
            y, m, d = date_str.split("-")
            return f"{d}/{m}/{y}"
        except Exception:
            return date_str
