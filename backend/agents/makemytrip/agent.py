"""
MakeMyTrip — Nova Act Agent

Phase 1 returns raw flight candidates from the results UI.
Later phases can harvest booking URLs, open them in fresh Nova sessions, and
extract offer details in a Cleartrip-style incremental flow.
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter, sleep
from typing import Callable

import yaml
from nova_act import ActGetResult, NovaAct, Workflow

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
    for k, v in kwargs.items():
        s = s.replace(f"{{{{{k}}}}}", v)
    return s


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


def _get_single_instruction(step_cfg: dict) -> str:
    path = _AGENT_DIR / step_cfg["instruction_file"]
    return path.read_text(encoding="utf-8").strip()


def _build_search_url(from_code: str, to_code: str, date_str: str, travel_class: str) -> str:
    """Build MMT direct flight search URL from a YYYY-MM-DD date string.

    Format: /flight/search?itinerary={FROM}-{TO}-{DD}/{MM}/{YYYY}&tripType=O&...
    Bypasses the search form entirely — browser lands directly on the results page.
    """
    y, m, d = date_str.split("-")
    date_url = f"{d}/{m}/{y}"           # DD/MM/YYYY as MMT expects in the URL
    class_codes = _CONFIG.get("class_codes") or {}
    cabin = class_codes.get(travel_class.lower().strip(), "E")
    base = _CONFIG["base_url"]
    return (
        f"{base}/flight/search"
        f"?itinerary={from_code}-{to_code}-{date_url}"
        f"&tripType=O&paxType=A-1_C-0_I-0&intl=false"
        f"&cabinClass={cabin}&lang=eng"
    )


def _parse_act_dict(output) -> dict | None:
    if isinstance(output, ActGetResult) and isinstance(getattr(output, "parsed_response", None), dict):
        return output.parsed_response
    if isinstance(output, dict):
        return output
    return None


def _normalize_coupons(coupon_list: list[dict]) -> list[dict]:
    for c in coupon_list:
        if "description" in c and isinstance(c["description"], str):
            c["description"] = c["description"].replace("\u20b5", "\u20b9")
    return coupon_list


def _run_coupon_extraction(nova, coupons_cfg: dict, price: int, result: dict) -> None:
    out = nova.act(
        _get_single_instruction(coupons_cfg),
        max_steps=coupons_cfg.get("max_steps", 12),
        schema=coupons_cfg.get("schema"),
    )
    coupons = (
        getattr(out, "parsed_response", None)
        if isinstance(out, ActGetResult)
        else (out if isinstance(out, list) else None)
    )
    coupon_list = _normalize_coupons(coupons or [])
    for c in coupon_list:
        c["price_after_coupon"] = max(0, price - int(c.get("discount", 0) or 0))
    result["coupons"] = coupon_list
    if coupon_list:
        result["best_price_after_coupon"] = min(c["price_after_coupon"] for c in coupon_list)


def _run_payment_step(nova, step_name: str, timing_key: str, result: dict, *, optional: bool = False):
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
            log.debug("Optional MMT payment step failed (%s): %s", step_name, e)
            return None
        raise
    timings[timing_key] = _elapsed_ms(started)
    return _parse_act_dict(output)


def _run_payment_probe(nova, result: dict) -> None:
    timings = result.setdefault("telemetry", {}).setdefault("timings_ms", {})
    probe_started = perf_counter()

    _run_payment_step(nova, "payment_insurance_continue", "insurance_continue_ms", result, optional=True)
    _run_payment_step(nova, "payment_skip_addons", "skip_addons_ms", result)
    _run_payment_step(nova, "payment_skip_addons_popup", "skip_addons_popup_ms", result, optional=True)
    _run_payment_step(nova, "payment_contact_continue", "contact_continue_ms", result, optional=True)
    _run_payment_step(nova, "payment_traveller_continue", "traveller_continue_ms", result, optional=True)

    parsed = _run_payment_step(nova, "extract_fare_breakdown", "payment_fare_extract_ms", result)
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


def _hhmm_to_minutes(value: str) -> int:
    h, m = str(value).strip().split(":")
    return int(h) * 60 + int(m)


def _new_offer_result(workflow_name: str, itinerary_url: str, flight_info: dict, *, payment_probe_enabled: bool) -> dict:
    return {
        "flight_number": flight_info.get("flight_number", ""),
        "airline": flight_info.get("airline", ""),
        "original_price": int(flight_info.get("price", 0) or 0),
        "fare_type": "",
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


def _extract_coupon_offer_branch(workflow_name: str, itinerary_url: str, flight_info: dict, headless: bool) -> dict:
    airline = flight_info.get("airline", "")
    flight_number = flight_info.get("flight_number", "")
    price = int(flight_info.get("price", 0) or 0)
    session_started = perf_counter()
    result = _new_offer_result(workflow_name, itinerary_url, flight_info, payment_probe_enabled=False)
    timings = result["telemetry"]["timings_ms"]
    try:
        get_or_create_workflow_definition(workflow_name)
        with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
            with NovaAct(workflow=wf, starting_page=itinerary_url, headless=headless, tty=False, ignore_https_errors=True) as nova:
                fare_cfg = _CONFIG["steps"].get("extract_fare_summary_booking")
                if fare_cfg:
                    try:
                        fare_started = perf_counter()
                        out = nova.act(
                            _get_single_instruction(fare_cfg),
                            max_steps=fare_cfg.get("max_steps", 12),
                            schema=fare_cfg.get("schema"),
                        )
                        parsed = _parse_act_dict(out)
                        if parsed:
                            base_fare = int(parsed.get("base_fare", 0) or 0)
                            taxes = int(parsed.get("taxes", 0) or 0)
                            convenience_fee = int(parsed.get("convenience_fee", 0) or 0)
                            total_fare = int(parsed.get("total_fare", 0) or 0)
                            if total_fare <= 0:
                                total_fare = base_fare + taxes + convenience_fee
                            result["fare_type"] = str(parsed.get("fare_type", "")).strip().upper()
                            result["original_price"] = total_fare or price
                            result["fare_breakdown"] = {
                                "base_fare": base_fare,
                                "taxes": taxes,
                                "convenience_fee": convenience_fee,
                                "total_fare": total_fare or price,
                            }
                        timings["fare_summary_ms"] = _elapsed_ms(fare_started)
                    except Exception as e:
                        log.debug("MMT fare summary extraction failed for %s %s: %s", airline, flight_number, e)
                coupons_cfg = _CONFIG["steps"].get("extract_coupons_from_booking_page")
                if coupons_cfg:
                    coupon_started = perf_counter()
                    _run_coupon_extraction(nova, coupons_cfg, result["original_price"] or price, result)
                    timings["coupon_ms"] = _elapsed_ms(coupon_started)
    except Exception as e:
        log.warning("MMT coupon branch failed for %s %s: %s", airline, flight_number, e)
        result["error"] = str(e)
    timings["coupon_branch_total_ms"] = _elapsed_ms(session_started)
    return result


def _extract_payment_offer_branch(workflow_name: str, itinerary_url: str, flight_info: dict, headless: bool) -> dict:
    airline = flight_info.get("airline", "")
    flight_number = flight_info.get("flight_number", "")
    session_started = perf_counter()
    result = _new_offer_result(workflow_name, itinerary_url, flight_info, payment_probe_enabled=True)
    timings = result["telemetry"]["timings_ms"]
    try:
        get_or_create_workflow_definition(workflow_name)
        with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
            with NovaAct(workflow=wf, starting_page=itinerary_url, headless=headless, tty=False, ignore_https_errors=True) as nova:
                _run_payment_probe(nova, result)
    except Exception as e:
        log.warning("MMT payment probe failed for %s %s: %s", airline, flight_number, e)
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


class MakeMyTripAgent:

    def _get_code(self, city: str) -> str:
        codes = _CONFIG.get("city_codes") or {}
        return codes.get(city.lower().strip(), city.upper()[:3])

    @staticmethod
    def _window_to_mmt_slot(window: list | None) -> str | None:
        """Map a [HH:MM, HH:MM] departure/arrival window to the closest MMT filter button label.

        MMT shows four time-slot buttons in both the Departure and Arrival filter panels:
            "Before 6 AM"   → 00:00 – 06:00
            "6 AM to 12 PM" → 06:00 – 12:00
            "12 PM to 6 PM" → 12:00 – 18:00
            "After 6 PM"    → 18:00 – 24:00

        The slot with the greatest minute-overlap with the requested window is chosen.
        Returns None if window is absent or unparseable (no filter applied).
        """
        if not window or len(window) != 2:
            return None
        try:
            start = _hhmm_to_minutes(window[0])
            end   = _hhmm_to_minutes(window[1])
        except (ValueError, AttributeError, TypeError):
            return None
        slots = [
            ("Before 6 AM",   0,    360),
            ("6 AM to 12 PM", 360,  720),
            ("12 PM to 6 PM", 720,  1080),
            ("After 6 PM",    1080, 1440),
        ]
        best_slot, best_overlap = None, 0
        for name, s_start, s_end in slots:
            overlap = max(0, min(end, s_end) - max(start, s_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_slot = name
        return best_slot

    @staticmethod
    def _filter_items_for_offers(items: list[dict], filters: dict | None) -> list[dict]:
        if not filters:
            return items
        result = items
        max_stops = filters.get("max_stops")
        if max_stops is not None:
            result = [f for f in result if f.get("stops", 99) <= max_stops]
        dep_window = filters.get("departure_window")
        if dep_window and len(dep_window) == 2:
            try:
                lo = _hhmm_to_minutes(dep_window[0])
                hi = _hhmm_to_minutes(dep_window[1])
            except (ValueError, AttributeError, TypeError):
                pass
            else:
                result = [
                    f for f in result
                    if f.get("departure") and lo <= _hhmm_to_minutes(f["departure"]) <= hi
                ]
        arr_window = filters.get("arrival_window")
        if arr_window and len(arr_window) == 2:
            try:
                lo = _hhmm_to_minutes(arr_window[0])
                hi = _hhmm_to_minutes(arr_window[1])
            except (ValueError, AttributeError, TypeError):
                pass
            else:
                result = [
                    f for f in result
                    if f.get("arrival") and lo <= _hhmm_to_minutes(f["arrival"]) <= hi
                ]
        return result

    @staticmethod
    def _apply_convenience_fee_from_first(offers_analysis: list[dict]) -> None:
        if not _CONFIG.get("reuse_probe_convenience_fee", True):
            return
        conv = None
        for offer in offers_analysis:
            fb = offer.get("fare_breakdown") or {}
            value = fb.get("convenience_fee")
            if isinstance(value, (int, float)) and value >= 0:
                conv = int(value)
                break
        if conv is None:
            return
        for offer in offers_analysis:
            fb = offer.get("fare_breakdown") or {}
            price = int(offer.get("original_price") or 0)
            if fb and fb.get("base_fare") is not None and fb.get("taxes") is not None:
                base = int(fb.get("base_fare") or 0)
                taxes = int(fb.get("taxes") or 0)
                offer["fare_breakdown"] = {
                    **fb,
                    "convenience_fee": conv,
                    "total_fare": base + taxes + conv,
                }
            elif price > 0:
                offer["fare_breakdown"] = {
                    "base_fare": max(0, price - conv),
                    "taxes": 0,
                    "convenience_fee": conv,
                    "total_fare": price,
                    "source": "fallback",
                }

    @staticmethod
    def _harvest_itinerary_urls(
        nova,
        items: list[dict],
        search_url: str,
        on_url_harvested: Callable[[int, dict, str], None] | None = None,
    ) -> list[dict]:
        top_n = _CONFIG.get("offers_top_n", 1)
        targets = sorted(items, key=lambda x: x.get("price", float("inf")))[:top_n]
        harvested: list[dict] = []
        combined_cfg = _CONFIG["steps"].get("book_then_continue")
        if not combined_cfg:
            log.warning("MMT book_then_continue step missing; cannot harvest URLs")
            return harvested
        for idx, flight in enumerate(targets):
            airline = flight["airline"]
            flight_number = flight["flight_number"]
            price = int(flight.get("price", 0) or 0)
            log.info("Harvest [%d/%d]: %s %s ₹%d", idx + 1, len(targets), airline, flight_number, price)
            harvest_started = perf_counter()
            try:
                if idx > 0:
                    nova.page.goto(search_url)
                    nova.page.wait_for_load_state("domcontentloaded")
                    wait_instruction = (_CONFIG["steps"].get("wait") or {}).get("instruction")
                    if wait_instruction:
                        nova.act(wait_instruction)
                instruction = _sub(
                    _get_single_instruction(combined_cfg),
                    airline=airline,
                    flight_number=flight_number,
                    price=str(price),
                )
                nova.act(instruction, max_steps=combined_cfg.get("max_steps", 12))
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
                    log.info("Harvest [%d/%d]: %s %s → %s", idx + 1, len(targets), airline, flight_number, itinerary_url[:80])
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
        log.info(
            "Searching MakeMyTrip: %s→%s date=%s class=%s filters=%s fetch_offers=%s",
            from_city,
            to_city,
            date,
            travel_class,
            filters,
            fetch_offers,
        )
        search_started = perf_counter()
        os.environ.pop("NOVA_ACT_API_KEY", None)

        workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_MMT") or _CONFIG["workflow_name"]
        from_code = self._get_code(from_city)
        to_code   = self._get_code(to_city)
        url = _build_search_url(from_code, to_code, date, travel_class)

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

            # Boot the SPA at the homepage first. /flight/search?... is a client-side route —
            # navigating to it cold returns a JSON/plain-text "200-OK" response from the server.
            # The React router handles the route only after the JS bundle is loaded from the root.
            homepage = _CONFIG["base_url"] + "/"
            with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf, \
                    NovaAct(workflow=wf, starting_page=homepage, headless=headless, tty=False,
                            ignore_https_errors=True) as nova:
                log.debug("Nova Act browser started for makemytrip.com (workflow=%s)", workflow_name)

                # Wait for the homepage to finish loading before navigating away.
                # MMT sets session cookies and auth tokens during homepage load; without this wait
                # goto(url) fires before cookies are written, and the flight API rejects the request.
                nova.page.wait_for_load_state("load")

                # ── Akamai _abck warm-up ──────────────────────────────────────────────────
                # Akamai Bot Manager writes its _abck challenge cookie via a JavaScript
                # sensor that executes AFTER window.onload. The sensor collects browser
                # fingerprints, sends them to Akamai's edge, and writes the _abck cookie
                # via an XHR — this takes 2-4 seconds. Navigating away immediately after
                # "load" fires leaves the browser without the cookie, so the flight data
                # API rejects requests ("NETWORK PROBLEM").
                #
                # Strategy: try networkidle (500ms quiet = sensor XHRs finished) with a
                # 6-second timeout, then enforce a minimum 3-second fixed dwell regardless.
                # If networkidle times out (analytics polling can prevent it), the fixed
                # sleep still covers the sensor's typical completion window.
                try:
                    nova.page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass  # analytics polling may prevent networkidle — fall through
                sleep(3)  # minimum dwell: Akamai sensor typically completes within 2-3s
                log.debug("MMT: Akamai warm-up complete — proceeding to fingerprint masking")

                # Mask headless browser signals that trigger MMT's bot detection.
                # Headless Chrome differs from real Chrome in several detectable ways:
                #   • UA contains "HeadlessChrome" → replaced via set_extra_http_headers (HTTP layer)
                #   • navigator.webdriver = true  → overridden via add_init_script (JS layer)
                #   • window.chrome is undefined  → add_init_script adds realistic mock
                #   • navigator.plugins is empty  → add_init_script adds common plugin entries
                # sec-ch-ua Client Hint headers are also set to match Chrome/122 for consistency.
                _REAL_UA = (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
                nova.page.context.set_extra_http_headers({
                    "User-Agent": _REAL_UA,
                    "sec-ch-ua": '"Google Chrome";v="122", "Not(A:Brand";v="24", "Chromium";v="122"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"macOS"',
                })
                # add_init_script registered BEFORE goto() — runs inside the search page document
                # before React scripts execute, so MMT sees the patched navigator/window.
                nova.page.add_init_script(f"""
(function() {{
    // User-Agent (JS-visible string)
    Object.defineProperty(navigator, 'userAgent', {{get: () => '{_REAL_UA}'}});

    // webdriver flag — primary Playwright/Selenium detection signal
    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});

    // window.chrome — absent or incomplete in headless Chromium
    if (!window.chrome) {{
        window.chrome = {{
            runtime: {{ id: undefined, connect: function() {{}}, sendMessage: function() {{}} }},
            app: {{}}, csi: function() {{}}, loadTimes: function() {{}}
        }};
    }}

    // navigator.plugins — empty in headless; real Chrome has 3-5 named entries
    Object.defineProperty(navigator, 'plugins', {{get: () => [
        {{name: 'PDF Viewer',          filename: 'internal-pdf-viewer', description: 'Portable Document Format'}},
        {{name: 'Chrome PDF Viewer',   filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
        {{name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: ''}},
        {{name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: ''}},
        {{name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: ''}}
    ]}});

    // navigator.languages — headless often uses a single or empty value
    Object.defineProperty(navigator, 'languages', {{get: () => ['en-US', 'en']}});

    // Hardware concurrency — headless Chromium defaults to 1; real Mac has 8-10
    Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => 8}});

    // Device memory — headless may return 0 or undefined; real Mac: 8 GB
    Object.defineProperty(navigator, 'deviceMemory', {{get: () => 8}});

    // outerWidth / outerHeight — 0 in headless (no browser UI chrome);
    // real browsers: outerHeight = innerHeight + ~88px for the address bar
    try {{
        Object.defineProperty(window, 'outerWidth',  {{get: () => screen.width  || 1440}});
        Object.defineProperty(window, 'outerHeight', {{get: () => (screen.height || 900)}});
    }} catch(e) {{}}

    // screen colorDepth / pixelDepth — be explicit; some headless builds differ
    try {{
        Object.defineProperty(screen, 'colorDepth', {{get: () => 24}});
        Object.defineProperty(screen, 'pixelDepth',  {{get: () => 24}});
    }} catch(e) {{}}

    // navigator.permissions — headless returns 'denied' for notifications
    // (no UI to show prompts). Real browsers return 'default' or 'prompt'.
    try {{
        const _origQuery = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = function(desc) {{
            if (desc && desc.name === 'notifications') {{
                return Promise.resolve({{ state: 'default', onchange: null }});
            }}
            return _origQuery(desc);
        }};
    }} catch(e) {{}}

    // Canvas fingerprint noise — headless Chromium renders canvas identically
    // across every session (same pixel hash = strong bot signal). A one-bit
    // flip in the top-left pixel makes each session unique without any visible
    // rendering change. The flip is applied and immediately reverted so it
    // doesn't affect page UI; only toDataURL() (used for fingerprinting) sees it.
    try {{
        const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function() {{
            if (this.width > 0 && this.height > 0) {{
                const ctx = this.getContext('2d');
                if (ctx) {{
                    const p = ctx.getImageData(0, 0, 1, 1);
                    p.data[0] ^= 1;            // flip one low bit
                    ctx.putImageData(p, 0, 0);
                    const res = _toDataURL.apply(this, arguments);
                    p.data[0] ^= 1;            // restore immediately
                    ctx.putImageData(p, 0, 0);
                    return res;
                }}
            }}
            return _toDataURL.apply(this, arguments);
        }};
    }} catch(e) {{}}

}})();
""")

                # Humanize homepage interaction before navigating to the search URL.
                # Akamai's sensor scores sessions with zero pointer events as bot-like.
                # Two gentle mouse moves + short pauses generate the mousemove/pointermove
                # events that real user sessions always contain.
                try:
                    nova.page.mouse.move(200, 300)
                    sleep(0.4)
                    nova.page.mouse.move(420, 360)
                    sleep(0.6)
                except Exception:
                    pass  # non-fatal if Playwright mouse API unavailable
                log.debug("MMT: homepage interaction complete — navigating to search URL")

                # Navigate to the search URL via client-side routing (JS router is now loaded).
                # This triggers the React router — flights render in the DOM, not a server response.
                nova.page.goto(url)
                nova.page.wait_for_load_state("domcontentloaded")

                # Wait for flight listings to finish rendering before extraction.
                # IMPORTANT: instruction must NOT include REFRESH — with the UA override active,
                # clicking REFRESH causes a full server reload that lands on the raw "200-OK" API
                # JSON response instead of staying in the React SPA. (Attempt 5 regression.)
                wait_instruction = (_CONFIG["steps"].get("wait") or {}).get("instruction")
                if wait_instruction:
                    nova.act(wait_instruction)

                # Page-drift guard: if the wait step caused navigation away from the search URL
                # (e.g. to the raw "200-OK" API endpoint), restore the search page before extraction.
                # The model cannot reliably recover from this on its own (hallucinates URLs).
                if "itinerary=" not in nova.page.url:
                    log.warning(
                        "MMT: page drifted after wait step (now: %s); restoring search page",
                        nova.page.url,
                    )
                    nova.page.goto(url)
                    nova.page.wait_for_load_state("domcontentloaded")

                # Apply departure / arrival time filters on the MMT UI before extraction.
                # This clicks the time-slot buttons ("Before 6 AM", "6 AM to 12 PM",
                # "12 PM to 6 PM", "After 6 PM") so the model only scrolls through the
                # filtered subset — faster extraction and fewer off-window results.
                # Skipped when no departure_window or arrival_window is requested.
                filter_cfg = _CONFIG["steps"].get("apply_filters")
                if filter_cfg and filters:
                    dep_slot = self._window_to_mmt_slot(filters.get("departure_window"))
                    arr_slot = self._window_to_mmt_slot(filters.get("arrival_window"))
                    if dep_slot or arr_slot:
                        filter_instruction = _sub(
                            _get_single_instruction(filter_cfg),
                            departure_slot=dep_slot or "none",
                            arrival_slot=arr_slot or "none",
                        )
                        filter_started = perf_counter()
                        nova.act(filter_instruction, max_steps=filter_cfg.get("max_steps", 8))
                        telemetry["timings_ms"]["apply_filters_ms"] = _elapsed_ms(filter_started)
                        log.info(
                            "MMT: UI filters applied — departure=%s arrival=%s",
                            dep_slot, arr_slot,
                        )

                extraction_cfg = _CONFIG["steps"]["extraction"]
                extraction_started = perf_counter()
                extracted = nova.act(
                    _get_single_instruction(extraction_cfg),
                    max_steps=max_steps,
                    schema=extraction_cfg["schema"],
                )
                telemetry["timings_ms"]["phase1_extract_ms"] = _elapsed_ms(extraction_started)

                items = None
                if isinstance(extracted, ActGetResult) and isinstance(getattr(extracted, "parsed_response", None), list):
                    items = extracted.parsed_response
                elif isinstance(extracted, list):
                    items = extracted

                if items is not None:
                    results = [
                        {
                            "platform": "makemytrip",
                            "from_city": from_city,
                            "to_city": to_city,
                            "date": date,
                            "class": travel_class,
                            **item,
                            "url": url,
                        }
                        for item in items
                    ]
                    log.info("MakeMyTrip returned %d flights for %s→%s on %s", len(results), from_city, to_city, date)
                else:
                    log.warning("MakeMyTrip extraction returned unexpected type: %s", type(extracted))

                if fetch_offers and results:
                    filtered_items = self._filter_items_for_offers(results, filters)
                    if filtered_items:
                        top_n = min(int(_CONFIG.get("offers_top_n", 1) or 1), len(filtered_items))
                        max_parallel = max(1, min(int(_CONFIG.get("max_parallel_offers", 2) or 2), top_n))
                        collect_convenience_fee = bool(_CONFIG.get("collect_convenience_fee", False))
                        convenience_fee_probe_index = int(_CONFIG.get("convenience_fee_probe_index", 0) or 0)
                        harvest_started = perf_counter()
                        harvested = self._harvest_itinerary_urls(nova, filtered_items, telemetry["search_url"])
                        telemetry["timings_ms"]["harvest_total_ms"] = _elapsed_ms(harvest_started)
                        telemetry["harvest"] = [h.get("telemetry", {}) for h in harvested]
                        offers_analysis: list[dict] = []
                        if harvested:
                            parallel_started = perf_counter()
                            if _CONFIG.get("use_parallel_offers", True):
                                with ThreadPoolExecutor(max_workers=max_parallel) as executor:
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
                                            offers_analysis.append(future.result())
                                        except Exception as e:
                                            fl = h["flight"]
                                            log.warning("MMT parallel extraction failed for %s %s: %s", fl.get("airline"), fl.get("flight_number"), e)
                                            offers_analysis.append(_new_offer_result(workflow_name, h.get("itinerary_url", ""), fl, payment_probe_enabled=False) | {"error": str(e)})
                            else:
                                for idx, h in enumerate(harvested):
                                    offers_analysis.append(
                                        self._extract_offers_from_itinerary_url(
                                            workflow_name,
                                            h["itinerary_url"],
                                            h["flight"],
                                            headless,
                                            collect_convenience_fee and idx == convenience_fee_probe_index,
                                        )
                                    )
                            telemetry["timings_ms"]["offer_parallel_wall_clock_ms"] = _elapsed_ms(parallel_started)
                            harvested_keys = [(h["flight"]["airline"], h["flight"]["flight_number"]) for h in harvested]
                            offers_analysis.sort(
                                key=lambda o: harvested_keys.index((o.get("airline"), o.get("flight_number")))
                                if (o.get("airline"), o.get("flight_number")) in harvested_keys
                                else 999
                            )
                            self._apply_convenience_fee_from_first(offers_analysis)
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
                            telemetry["timings_ms"]["total_search_ms"] = _elapsed_ms(search_started)
                            return {"telemetry": telemetry, "flights": results, "offers_analysis": offers_analysis}

            if fetch_offers:
                telemetry["timings_ms"]["total_search_ms"] = _elapsed_ms(search_started)
                return {"telemetry": telemetry, "flights": results, "offers_analysis": []}
            return results
        except Exception as e:
            return ActExceptionHandler.handle(e, "MakeMyTrip", context)
