"""
Ixigo — Nova Act Agent

Phase 1: Extract flight listings from ixigo.com (bot-detection hardened).
Phase 3: For specific target flights, click Book and extract coupons in-session.

See docs/BOT_DETECTION_GUIDE.md for the multi-layer anti-detection approach.
"""

import os
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter, sleep

from nova_act import ActGetResult, NovaAct, Workflow

from logger import get_logger
from nova_auth import get_or_create_workflow_definition
from agents.act_handler import ActExceptionHandler
from nova.flight_normalizer import FlightNormalizer

log = get_logger(__name__)

_AGENT_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _AGENT_DIR / "config.yaml"
with open(_CONFIG_PATH, encoding="utf-8") as f:
    _CONFIG = yaml.safe_load(f)

_REAL_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

_STEALTH_INIT_SCRIPT = f"""
(function() {{
    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
    Object.defineProperty(navigator, 'userAgent', {{get: () => '{_REAL_UA}'}});

    if (!window.chrome) {{
        window.chrome = {{
            runtime: {{ id: undefined, connect: function() {{}}, sendMessage: function() {{}} }},
            app: {{}}, csi: function() {{}}, loadTimes: function() {{}}
        }};
    }}

    Object.defineProperty(navigator, 'plugins', {{get: () => [
        {{name: 'PDF Viewer',          filename: 'internal-pdf-viewer', description: 'Portable Document Format'}},
        {{name: 'Chrome PDF Viewer',   filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
        {{name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: ''}},
        {{name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: ''}},
        {{name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: ''}}
    ]}});

    Object.defineProperty(navigator, 'languages', {{get: () => ['en-US', 'en']}});
    Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => 8}});
    Object.defineProperty(navigator, 'deviceMemory', {{get: () => 8}});

    try {{
        Object.defineProperty(window, 'outerWidth',  {{get: () => screen.width  || 1440}});
        Object.defineProperty(window, 'outerHeight', {{get: () => (screen.height || 900)}});
    }} catch(e) {{}}

    try {{
        Object.defineProperty(screen, 'colorDepth', {{get: () => 24}});
        Object.defineProperty(screen, 'pixelDepth',  {{get: () => 24}});
    }} catch(e) {{}}

    try {{
        const _origQuery = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = function(desc) {{
            if (desc && desc.name === 'notifications') {{
                return Promise.resolve({{ state: 'default', onchange: null }});
            }}
            return _origQuery(desc);
        }};
    }} catch(e) {{}}

    try {{
        const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function() {{
            if (this.width > 0 && this.height > 0) {{
                const ctx = this.getContext('2d');
                if (ctx) {{
                    const p = ctx.getImageData(0, 0, 1, 1);
                    p.data[0] ^= 1;
                    ctx.putImageData(p, 0, 0);
                    const res = _toDataURL.apply(this, arguments);
                    p.data[0] ^= 1;
                    ctx.putImageData(p, 0, 0);
                    return res;
                }}
            }}
            return _toDataURL.apply(this, arguments);
        }};
    }} catch(e) {{}}
}})();
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_instruction(step_cfg: dict) -> str:
    path = _AGENT_DIR / step_cfg["instruction_file"]
    return path.read_text(encoding="utf-8").strip()


def _sub(s: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        s = s.replace(f"{{{{{k}}}}}", v)
    return s


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


def _hhmm_to_minutes(value: str) -> int:
    h, m = str(value).strip().split(":")
    return int(h) * 60 + int(m)


def _resolve_time_buckets(window: list | None, buckets: list[dict]) -> list[str]:
    """Map a [HH:MM, HH:MM] window to overlapping Ixigo time bucket values."""
    if not window or len(window) != 2:
        return []
    try:
        lo = _hhmm_to_minutes(window[0])
        hi = _hhmm_to_minutes(window[1])
    except (ValueError, AttributeError, TypeError):
        return []
    selected = []
    for b in buckets:
        b_start = b["start"]
        b_end = b["end"]
        if max(lo, b_start) < min(hi, b_end):
            selected.append(b["ixigo_value"])
    if len(selected) == len(buckets):
        return []
    return selected


def _normalize_coupons(coupon_list: list[dict]) -> list[dict]:
    for c in coupon_list:
        if "description" in c and isinstance(c["description"], str):
            c["description"] = c["description"].replace("\u20b5", "\u20b9")
    return coupon_list


def _backfill_booking_urls(flights: list[dict], offers_analysis: list[dict]) -> None:
    """Set booking_url and book_url on each flight that has a matching offer (by airline + flight_number)."""
    key_to_url: dict[tuple[str, str], str] = {}
    for o in offers_analysis:
        url = o.get("booking_url")
        if url:
            key_to_url[(str(o.get("airline", "")).strip(), str(o.get("flight_number", "")).strip())] = url
    for f in flights:
        k = (str(f.get("airline", "")).strip(), str(f.get("flight_number", "")).strip())
        if k in key_to_url:
            url = key_to_url[k]
            f["booking_url"] = url
            f["book_url"] = url  # normalizer reads book_url


def _build_filtered_with_offers(
    raw_flights: list[dict],
    offers_analysis: list[dict],
    filters: dict | None,
) -> list[dict]:
    """
    Build app-ready list: all filtered flights, with optional offer data for the first N.

    Each item has canonical flight fields (platform, airline, flight_number, departure,
    arrival, duration, stops, price, book_url, from_city, to_city, date, travel_class).
    For the first len(offers_analysis) items we add an "offers" object with
    booking_url, fare_details, coupons, best_price_after_coupon; for the rest offers is null.
    """
    normalizer = FlightNormalizer()
    filtered = normalizer.normalize(raw_flights, filters=filters or {})
    n = len(offers_analysis)
    out: list[dict] = []
    for i, flight in enumerate(filtered):
        item = dict(flight)
        if i < n:
            o = offers_analysis[i]
            item["offers"] = {
                "booking_url": o.get("booking_url"),
                "fare_details": o.get("fare_details") or {},
                "coupons": o.get("coupons") or [],
                "best_price_after_coupon": o.get("best_price_after_coupon"),
            }
        else:
            item["offers"] = None
        out.append(item)
    return out


def _apply_stealth(nova) -> None:
    """Apply all bot-detection countermeasures to a Nova session."""
    nova.page.wait_for_load_state("load")

    try:
        nova.page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    sleep(2)

    nova.page.context.set_extra_http_headers({
        "User-Agent": _REAL_UA,
        "sec-ch-ua": '"Google Chrome";v="122", "Not(A:Brand";v="24", "Chromium";v="122"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    })

    nova.page.add_init_script(_STEALTH_INIT_SCRIPT)

    try:
        nova.page.mouse.move(200, 300)
        sleep(0.4)
        nova.page.mouse.move(420, 360)
        sleep(0.6)
    except Exception:
        pass


def _wait_for_results(nova, url: str) -> None:
    """Navigate to search URL and wait for results. Dynamic wait for flight-list when configured, else static sleep (racing logic)."""
    nova.page.goto(url)
    nova.page.wait_for_load_state("domcontentloaded")

    selector = _CONFIG.get("wait_for_selector")
    timeout_ms = _CONFIG.get("wait_for_selector_timeout_ms", 15000)
    if selector and isinstance(selector, str) and selector.strip():
        try:
            log.info("Ixigo: waiting for results container %s (max %d ms)", selector, timeout_ms)
            nova.page.wait_for_selector(selector.strip(), state="visible", timeout=timeout_ms)
            sleep(1)  # brief pause for hydration after container is visible (avoids skeleton loaders)
        except Exception as e:
            log.warning("Ixigo: wait_for_selector %r failed (%s), falling back to static sleep", selector, e)
            sleep(4)
    else:
        sleep(4)

    if "search/result/flight" not in nova.page.url:
        log.warning("Ixigo: page drifted (now: %s); restoring", nova.page.url)
        nova.page.goto(url)
        nova.page.wait_for_load_state("domcontentloaded")
        if selector and isinstance(selector, str) and selector.strip():
            try:
                nova.page.wait_for_selector(selector.strip(), state="visible", timeout=timeout_ms)
            except Exception:
                pass
        sleep(2)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IxigoAgent:
    def _process_one_target(self, nova, flight: dict, url: str, idx: int, total: int) -> dict:
        """Process a single target in an existing session: book (or goto url) + extract coupons. Returns one offer dict."""
        book_cfg = _CONFIG["steps"].get("book_then_continue")
        coupons_cfg = _CONFIG["steps"].get("extract_coupons_from_booking_page")
        conv_fee = _CONFIG.get("convenience_fee", 0)
        airline = flight.get("airline", "")
        flight_number = flight.get("flight_number", "")
        price = int(flight.get("price", 0) or 0)

        offer: dict = {
            "flight_number": flight_number,
            "airline": airline,
            "original_price": price,
            "fare_details": {},
            "coupons": [],
            "best_price_after_coupon": None,
            "booking_url": None,
        }
        flight_start = perf_counter()

        try:
            direct_url = (flight.get("book_url") or flight.get("booking_url") or "").strip()
            if direct_url and direct_url.startswith("http"):
                nova.page.goto(direct_url)
                nova.page.wait_for_load_state("domcontentloaded")
                sleep(2)
                offer["booking_url"] = nova.page.url
                log.info("Offers [%d/%d]: used Phase 1 book_url → %s", idx + 1, total, nova.page.url[:80])
            else:
                _wait_for_results(nova, url)
                instruction = _sub(
                    _get_instruction(book_cfg),
                    airline=airline,
                    flight_number=flight_number,
                    price=str(price),
                )
                nova.act(instruction, max_steps=book_cfg.get("max_steps", 30))
                offer["booking_url"] = nova.page.url
                log.info("Offers [%d/%d]: on booking page → %s", idx + 1, total, nova.page.url[:80])

            out = nova.act(
                _get_instruction(coupons_cfg),
                max_steps=coupons_cfg.get("max_steps", 25),
                schema=coupons_cfg.get("schema"),
            )
            parsed = (
                getattr(out, "parsed_response", None)
                if isinstance(out, ActGetResult)
                else (out if isinstance(out, dict) else None)
            )

            if isinstance(parsed, dict):
                fare_details = parsed.get("fare_details") or {}
                fare_details["convenience_fee"] = conv_fee
                fare_total = int(fare_details.get("total", 0) or 0)
                fare_details["final_price"] = fare_total + conv_fee
                offer["fare_details"] = fare_details
                if fare_details:
                    log.info(
                        "Offers [%d/%d]: fare base=₹%s taxes=₹%s total=₹%s +conv=₹%d → final=₹%s",
                        idx + 1, total,
                        fare_details.get("base_fare"), fare_details.get("taxes"),
                        fare_total, conv_fee, fare_details["final_price"],
                    )
                coupon_list = _normalize_coupons(parsed.get("coupons") or [])
            else:
                coupon_list = _normalize_coupons(parsed if isinstance(parsed, list) else [])

            final_price = int(offer.get("fare_details", {}).get("final_price", price) or price)
            for c in coupon_list:
                c["price_after_coupon"] = max(0, final_price - int(c.get("discount", 0) or 0))
            offer["coupons"] = coupon_list
            if coupon_list:
                offer["best_price_after_coupon"] = min(c["price_after_coupon"] for c in coupon_list)
            log.info("Offers [%d/%d]: %d coupons extracted", idx + 1, total, len(coupon_list))
        except Exception as e:
            log.warning("Offers [%d/%d]: failed for %s %s: %s", idx + 1, total, airline, flight_number, e)
            offer["error"] = str(e)

        offer["session_ms"] = _elapsed_ms(flight_start)
        return offer

    def _run_one_offer_in_new_session(self, target: dict, url: str, idx: int, total: int) -> dict:
        """Open a new Nova session, load search page, process this one target. Returns one offer dict (for parallel P3)."""
        workflow_name = _CONFIG["workflow_name"]
        homepage = _CONFIG["base_url"] + "/"
        get_or_create_workflow_definition(workflow_name)
        headless = os.environ.get("FAREWISE_HEADED", "0") != "1"
        with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf, \
                NovaAct(workflow=wf, starting_page=homepage, headless=headless,
                        tty=False, ignore_https_errors=True) as nova:
            _apply_stealth(nova)
            _wait_for_results(nova, url)
            return self._process_one_target(nova, target, url, idx, total)

    def _run_offer_loop_parallel(self, targets: list[dict], url: str) -> list[dict]:
        """Run one Nova session per target in parallel. Returns offers_analysis in target order."""
        book_cfg = _CONFIG["steps"].get("book_then_continue")
        coupons_cfg = _CONFIG["steps"].get("extract_coupons_from_booking_page")
        if not book_cfg or not coupons_cfg:
            return []
        total = len(targets)
        max_workers = min(_CONFIG.get("max_parallel_offers", 2), total)
        log.info("Ixigo fetch_offers: parallel mode, %d sessions for %d targets", max_workers, total)
        offers_analysis: list[dict] = [None] * total
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._run_one_offer_in_new_session, t, url, idx, total): idx
                for idx, t in enumerate(targets)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    offers_analysis[idx] = future.result()
                except Exception as e:
                    log.warning("Parallel offer [%d/%d] failed: %s", idx + 1, total, e)
                    t = targets[idx]
                    offers_analysis[idx] = {
                        "flight_number": t.get("flight_number", ""),
                        "airline": t.get("airline", ""),
                        "original_price": t.get("price", 0),
                        "fare_details": {},
                        "coupons": [],
                        "best_price_after_coupon": None,
                        "booking_url": None,
                        "error": str(e),
                        "session_ms": 0,
                    }
        return [o for o in offers_analysis if o is not None]

    def _run_offer_loop(self, nova, targets: list[dict], url: str) -> list[dict]:
        """Sequential: in the current session, for each target Book (or goto book_url) + extract coupons."""
        book_cfg = _CONFIG["steps"].get("book_then_continue")
        coupons_cfg = _CONFIG["steps"].get("extract_coupons_from_booking_page")
        if not book_cfg or not coupons_cfg:
            return []
        top_n = _CONFIG.get("offers_top_n", 2)
        targets = targets[:top_n]
        total = len(targets)
        offers_analysis = []
        for idx, flight in enumerate(targets):
            airline = flight.get("airline", "")
            flight_number = flight.get("flight_number", "")
            price = int(flight.get("price", 0) or 0)
            log.info("Offers [%d/%d]: %s %s ₹%d", idx + 1, total, airline, flight_number, price)
            offer = self._process_one_target(nova, flight, url, idx, total)
            offers_analysis.append(offer)
        return offers_analysis

    def _get_code(self, city: str) -> str:
        codes = _CONFIG.get("city_codes") or {}
        return codes.get(city.lower().strip(), city.upper()[:3])

    def _format_date(self, date_str: str) -> str:
        """YYYY-MM-DD -> DDMMYYYY"""
        try:
            parts = date_str.split("-")
            return f"{parts[2]}{parts[1]}{parts[0]}"
        except Exception:
            return date_str.replace("-", "")

    def _build_search_url(self, from_city, to_city, date, travel_class, filters=None):
        from_code = self._get_code(from_city)
        to_code = self._get_code(to_city)
        date_ixigo = self._format_date(date)
        class_code = _CONFIG.get("class_codes", {}).get(travel_class.lower(), "e")

        url = (
            f"{_CONFIG['base_url']}/search/result/flight"
            f"?from={from_code}&to={to_code}&date={date_ixigo}"
            f"&adults=1&children=0&infants=0&class={class_code}&intl=n"
        )

        # Sort: Ixigo sort_type = cheapest | quickest | earliest | best; default cheapest
        sort_by = (filters or {}).get("sort_by", "price")
        ixigo_sort = {"price": "cheapest", "duration": "quickest", "departure": "earliest"}.get(
            sort_by, "cheapest"
        )
        url += f"&sort_type={ixigo_sort}"

        if not filters:
            return url

        max_stops = filters.get("max_stops")
        if max_stops is not None:
            url += f"&stops={int(max_stops)}"

        buckets = _CONFIG.get("time_buckets", [])
        if buckets:
            dep_vals = _resolve_time_buckets(filters.get("departure_window"), buckets)
            if dep_vals:
                url += "&takeOff=" + ",".join(dep_vals)

            arr_vals = _resolve_time_buckets(filters.get("arrival_window"), buckets)
            if arr_vals:
                url += "&landing=" + ",".join(arr_vals)

        return url

    # -----------------------------------------------------------------
    # Phase 1: Extract flights (optionally Phase 3 in same session)
    # -----------------------------------------------------------------
    def search(
        self,
        from_city: str,
        to_city: str,
        date: str,
        travel_class: str = "economy",
        filters: dict | None = None,
        fetch_offers: bool = False,
    ) -> list[dict] | dict:
        """Extract flight listings from Ixigo.

        When fetch_offers=False (default): returns a list of flight dicts.
        When fetch_offers=True: runs Phase 2 (normalize) and Phase 3 (book + coupons)
        in the same browser session and returns
        { "telemetry": {...}, "flights": [...], "offers_analysis": [...] }.
        """
        log.info(
            "Searching Ixigo: %s→%s date=%s class=%s filters=%s fetch_offers=%s",
            from_city, to_city, date, travel_class, filters, fetch_offers,
        )

        workflow_name = _CONFIG["workflow_name"]
        url = self._build_search_url(from_city, to_city, date, travel_class, filters)
        log.debug("Ixigo search URL: %s", url)
        get_or_create_workflow_definition(workflow_name)
        headless = os.environ.get("FAREWISE_HEADED", "0") != "1"
        max_steps = int(os.environ.get("NOVA_ACT_MAX_STEPS", _CONFIG.get("max_steps_default", 50)))

        results: list[dict] = []
        overall_start = perf_counter()
        pending_parallel: tuple[list[dict], str] | None = None  # (targets, url) when P3 runs parallel after block

        try:
            homepage = _CONFIG["base_url"] + "/"
            with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf, \
                    NovaAct(workflow=wf, starting_page=homepage, headless=headless,
                            tty=False, ignore_https_errors=True) as nova:

                _apply_stealth(nova)
                _wait_for_results(nova, url)
                # Skeleton prevention: brief dwell so results list can hydrate before extraction scroll
                sleep(3)
                log.debug("Ixigo: post-wait dwell (3s) for results hydration")

                extraction_cfg = _CONFIG["steps"]["extraction"]
                extracted = nova.act(
                    _get_instruction(extraction_cfg),
                    max_steps=max_steps,
                    schema=extraction_cfg["schema"],
                )

                items = None
                if isinstance(extracted, ActGetResult) and isinstance(
                    getattr(extracted, "parsed_response", None), list
                ):
                    items = extracted.parsed_response
                elif isinstance(extracted, list):
                    items = extracted

                if items is not None:
                    results = [
                        {
                            "platform": "ixigo",
                            "from_city": from_city,
                            "to_city": to_city,
                            "date": date,
                            "class": travel_class,
                            **item,
                        }
                        for item in items
                    ]
                    log.info("Ixigo Phase 1: %d flights extracted for %s→%s", len(results), from_city, to_city)
                else:
                    log.warning("Ixigo extraction returned unexpected type: %s", type(extracted))

                if fetch_offers and results:
                    normalizer = FlightNormalizer()
                    filtered = normalizer.normalize(results, filters=filters or {})
                    top_n = _CONFIG.get("offers_top_n", 2)
                    targets = filtered[:top_n]
                    use_parallel = _CONFIG.get("offers_parallel") and len(targets) > 1
                    if use_parallel:
                        log.info("Ixigo fetch_offers: parallel (after P1), %d targets", len(targets))
                        pending_parallel = (targets, url)
                    else:
                        log.info("Ixigo fetch_offers (same session): %d targets", len(targets))
                        offers_analysis = self._run_offer_loop(nova, targets, url)
                        _backfill_booking_urls(results, offers_analysis)
                        telemetry = {"search_url": url, "timings_ms": {"total_ms": _elapsed_ms(overall_start)}}
                        filtered = _build_filtered_with_offers(results, offers_analysis, filters)
                        return {
                            "telemetry": telemetry,
                            "flights": results,
                            "filtered": filtered,
                            "offers_analysis": offers_analysis,
                        }
                if fetch_offers and not results:
                    telemetry = {"search_url": url, "timings_ms": {"total_ms": _elapsed_ms(overall_start)}}
                    return {"telemetry": telemetry, "flights": [], "filtered": [], "offers_analysis": []}

            # After closing the extraction session: run P3 in parallel if requested
            if pending_parallel is not None:
                targets, offer_url = pending_parallel
                offers_analysis = self._run_offer_loop_parallel(targets, offer_url)
                _backfill_booking_urls(results, offers_analysis)
                telemetry = {"search_url": url, "timings_ms": {"total_ms": _elapsed_ms(overall_start)}}
                filtered = _build_filtered_with_offers(results, offers_analysis, filters)
                return {
                    "telemetry": telemetry,
                    "flights": results,
                    "filtered": filtered,
                    "offers_analysis": offers_analysis,
                }

            return results
        except Exception as e:
            return ActExceptionHandler.handle(e, "Ixigo", {"from": from_city, "to": to_city})

    # -----------------------------------------------------------------
    # Phase 3: Book + extract coupons for specific targets
    # -----------------------------------------------------------------
    def fetch_offers(
        self,
        targets: list[dict],
        from_city: str,
        to_city: str,
        date: str,
        travel_class: str = "economy",
        filters: dict | None = None,
    ) -> dict:
        """For each target flight, click Book and extract coupons in one session.

        `targets` should be the Phase-2-normalized top flights (already filtered/sorted).
        Use search(..., fetch_offers=True) for a single-session flow (extract + offers).
        """
        workflow_name = _CONFIG["workflow_name"]
        url = self._build_search_url(from_city, to_city, date, travel_class, filters)
        get_or_create_workflow_definition(workflow_name)
        headless = os.environ.get("FAREWISE_HEADED", "0") != "1"

        top_n = _CONFIG.get("offers_top_n", 2)
        targets = targets[:top_n]
        log.info("Ixigo fetch_offers: %d targets on %s→%s", len(targets), from_city, to_city)

        telemetry: dict = {"search_url": url, "timings_ms": {}}
        overall_start = perf_counter()
        use_parallel = _CONFIG.get("offers_parallel") and len(targets) > 1

        try:
            if use_parallel:
                offers_analysis = self._run_offer_loop_parallel(targets, url)
            else:
                homepage = _CONFIG["base_url"] + "/"
                with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf, \
                        NovaAct(workflow=wf, starting_page=homepage, headless=headless,
                                tty=False, ignore_https_errors=True) as nova:
                    _apply_stealth(nova)
                    _wait_for_results(nova, url)
                    offers_analysis = self._run_offer_loop(nova, targets, url)
        except Exception as e:
            log.error("Ixigo fetch_offers failed: %s", e)
            offers_analysis = []

        telemetry["timings_ms"]["total_ms"] = _elapsed_ms(overall_start)
        return {"telemetry": telemetry, "offers_analysis": offers_analysis}
