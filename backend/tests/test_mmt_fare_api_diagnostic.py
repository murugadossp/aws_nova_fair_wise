"""
Diagnostic: capture every XHR request/response triggered by MMT's "Getting More Fares..." popup.

Goal: identify the fare comparison API endpoint, its headers, request payload, and response
so we can decide how to fix Phase 2 harvest bot detection.

Run (headed so we can see the UI):
    cd backend && FAREWISE_HEADED=1 .venv/bin/python tests/test_mmt_fare_api_diagnostic.py

Output:
    logs/fare_api_diagnostic.json  — full capture (URLs, headers, bodies)
    logs/agent_mmt_fare_diagnostic_*.log — human-readable log
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter, sleep

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from nova_auth import get_or_create_workflow_definition
from nova_act import NovaAct, Workflow

log = get_logger(__name__)

_BASE_URL   = "https://www.makemytrip.com"
_WORKFLOW   = "farewise-makemytrip"
_REAL_UA    = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_SKIP_EXTS  = {".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico",
               ".woff", ".woff2", ".ttf", ".gif", ".webp", ".map"}


def _is_api_url(url: str) -> bool:
    """True for XHR/fetch calls — skip static assets."""
    for ext in _SKIP_EXTS:
        if ext in url.split("?")[0][-10:]:
            return False
    return True


def _build_url(days: int = 7) -> str:
    travel = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")
    y, m, d = travel.split("-")
    return (
        f"{_BASE_URL}/flight/search"
        f"?itinerary=BOM-DEL-{d}/{m}/{y}"
        f"&tripType=O&paxType=A-1_C-0_I-0&intl=false&cabinClass=E&lang=eng"
    )


def run_diagnostic():
    url = _build_url(days=7)
    log.info("Search URL: %s", url)

    captured_requests:  list[dict] = []
    captured_responses: list[dict] = []

    # ── Playwright event callbacks ──────────────────────────────────────────────
    def on_request(request):
        if not _is_api_url(request.url):
            return
        entry = {
            "url":       request.url,
            "method":    request.method,
            "headers":   dict(request.headers),
            "post_data": request.post_data,
        }
        captured_requests.append(entry)
        log.info("→ REQ  %s %s", request.method, request.url[:180])
        if request.post_data:
            log.info("       BODY: %s", str(request.post_data)[:300])

    def on_response(response):
        if not _is_api_url(response.url):
            return
        body_preview = ""
        try:
            # response.text() is synchronous in Playwright sync API —
            # safe to call here; blocks until body is fully buffered.
            body_preview = response.text()[:600]
        except Exception as e:
            body_preview = f"<unreadable: {e}>"
        entry = {
            "url":          response.url,
            "status":       response.status,
            "headers":      dict(response.headers),
            "body_preview": body_preview,
        }
        captured_responses.append(entry)
        status_tag = "✅" if response.status < 400 else "❌"
        log.info("← RESP %s [%d] %s", status_tag, response.status, response.url[:150])
        if body_preview:
            log.info("       BODY: %s", body_preview[:300])

    # ── Boot sequence (mirrors agent.py exactly) ────────────────────────────────
    headless = os.environ.get("FAREWISE_HEADED", "0") != "1"
    get_or_create_workflow_definition(_WORKFLOW)

    with Workflow(workflow_definition_name=_WORKFLOW, model_id="nova-act-latest") as wf, \
            NovaAct(workflow=wf, starting_page=_BASE_URL + "/", headless=headless,
                    tty=False, ignore_https_errors=True) as nova:

        page = nova.page

        # 1. Homepage boot
        page.wait_for_load_state("load")

        # 2. Akamai _abck warm-up (same as agent.py)
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        sleep(3)
        log.info("Akamai warm-up complete")

        # 3. HTTP + JS fingerprint masking (same as agent.py)
        page.context.set_extra_http_headers({
            "User-Agent":          _REAL_UA,
            "sec-ch-ua":           '"Google Chrome";v="122", "Not(A:Brand";v="24", "Chromium";v="122"',
            "sec-ch-ua-mobile":    "?0",
            "sec-ch-ua-platform":  '"macOS"',
        })
        page.add_init_script(f"""
(function() {{
    Object.defineProperty(navigator, 'userAgent',           {{get: () => '{_REAL_UA}'}});
    Object.defineProperty(navigator, 'webdriver',           {{get: () => undefined}});
    Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => 8}});
    Object.defineProperty(navigator, 'deviceMemory',        {{get: () => 8}});
    Object.defineProperty(navigator, 'languages',           {{get: () => ['en-US','en']}});
    if (!window.chrome) {{
        window.chrome = {{runtime: {{id: undefined}}, app: {{}}}};
    }}
}})();
""")

        # 4. Humanized mouse + navigate
        page.mouse.move(200, 300); sleep(0.4)
        page.mouse.move(420, 360); sleep(0.6)
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")
        sleep(4)   # let results render
        log.info("On search results page: %s", page.url[:100])

        # ── Attach listeners BEFORE clicking ──────────────────────────────────
        log.info("Attaching request/response listeners...")
        page.on("request",  on_request)
        page.on("response", on_response)

        # ── Click "View Prices" on the first visible flight ────────────────────
        log.info("Clicking first 'View Prices' button...")
        clicked = False
        for selector in [
            "text=View Prices",
            "[class*='viewPrice']",
            "[class*='bookBtn']",
            "button:has-text('Book')",
            "[class*='btnBook']",
        ]:
            try:
                loc = page.locator(selector).first
                loc.wait_for(timeout=5000, state="visible")
                loc.click()
                log.info("Clicked selector: %s", selector)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            # Fallback: ask Nova Act to click it
            log.warning("Direct Playwright click failed — using nova.act fallback")
            nova.act(
                "Find the first flight card on the page and click its 'View Prices' button. "
                "Do not interact with anything else.",
                max_steps=5,
            )

        # ── Wait 35 seconds for fare API to attempt to load ───────────────────
        log.info("Waiting 35s for fare API calls to complete...")
        for tick in range(7):
            sleep(5)
            api_calls = [r for r in captured_requests if _is_fare_related(r["url"])]
            log.info("  [%ds] %d total requests captured, %d fare-related",
                     (tick + 1) * 5, len(captured_requests), len(api_calls))

        # ── Report ─────────────────────────────────────────────────────────────
        log.info("\n" + "=" * 70)
        log.info("DIAGNOSTIC SUMMARY")
        log.info("=" * 70)
        log.info("Total requests captured:  %d", len(captured_requests))
        log.info("Total responses captured: %d", len(captured_responses))

        fare_reqs = [r for r in captured_requests if _is_fare_related(r["url"])]
        fare_resp = [r for r in captured_responses if _is_fare_related(r["url"])]
        log.info("Fare-related requests:    %d", len(fare_reqs))
        log.info("Fare-related responses:   %d", len(fare_resp))

        log.info("\n--- ALL API REQUESTS ---")
        for r in captured_requests:
            log.info("  %s %s", r["method"], r["url"])

        log.info("\n--- FARE-RELATED RESPONSES (key target) ---")
        for r in fare_resp:
            log.info("  [%d] %s", r["status"], r["url"])
            log.info("       body: %s", r["body_preview"][:400])

        # ── Dump everything to JSON ────────────────────────────────────────────
        out_path = Path(__file__).resolve().parent.parent / "logs" / "fare_api_diagnostic.json"
        out_path.parent.mkdir(exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "search_url": url,
                "all_requests":       captured_requests,
                "all_responses":      captured_responses,
                "fare_requests":      fare_reqs,
                "fare_responses":     fare_resp,
            }, f, indent=2, default=str)
        log.info("\nFull diagnostic saved to: %s", out_path)


def _is_fare_related(url: str) -> bool:
    keywords = ["fare", "price", "offer", "booking", "flight", "itinerary", "api", "graphql"]
    u = url.lower()
    return any(k in u for k in keywords) and _is_api_url(url)


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("mmt_fare_diagnostic")
    log.info("Logs → %s", log_path)
    run_diagnostic()
