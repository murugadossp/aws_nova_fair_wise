# MakeMyTrip — Bot Detection Debug Log (2026-03-10)

This file documents the full sequence of attempts to get the MMT agent working, what each attempt revealed, and why each fix was applied. It is intended as a reference for future debugging sessions and for understanding the final state of the agent.

---

## The core problem

MakeMyTrip has multi-layer bot detection. Every approach taken either hit a different detection layer or revealed a new one. The journey had **five distinct phases**.

---

## Attempt 1 — Form filling via `search_form.md` (original approach)

**Approach:** Open `https://www.makemytrip.com/flights/` (homepage), use a Nova Act instruction to fill origin/destination/date fields and click "SEARCH".

**What happened:** MMT's bot detection triggers during interactive form filling — login popups appear mid-session, JavaScript challenges fire, and field-filling events (typing into autocomplete, datepicker interaction) all set off fingerprinting. The search rarely completes, and when it does the results page is empty.

**Diagnosis:** Interactive form filling generates too many bot-like signals. Every keypress, click, and form event is monitored.

---

## Attempt 2 — Direct URL as `starting_page`

**Approach:** Skip the form entirely. Build the results URL directly (`_build_search_url()`) and pass it as `starting_page=url` to `NovaAct`. The URL format inferred from the real MMT UI:
```
https://www.makemytrip.com/flight/search
  ?itinerary={FROM}-{TO}-{DD}/{MM}/{YYYY}
  &tripType=O&paxType=A-1_C-0_I-0&intl=false
  &cabinClass={E|B|P|F}&lang=eng
```

**What happened:** Chrome navigated to that URL and showed "200-OK" as plain text — Chrome's response viewer for a non-HTML response. The model saw an empty page.

**Diagnosis:** `makemytrip.com/flight/search?...` is a **server-side API endpoint**, not a web page. It returns JSON (or a plain "200-OK") when cold-navigated because the React SPA has not been bootstrapped. The `/flight/search` route is a client-side route handled by the JavaScript router, which only runs after the SPA HTML + JS bundle is loaded from the homepage.

**Fix applied:** Change `starting_page` to the homepage (`https://www.makemytrip.com/`), then call `nova.page.goto(url)` to trigger client-side routing after the SPA is loaded.

---

## Attempt 3 — Homepage as `starting_page`, immediate `goto(url)`

**Approach:**
```python
NovaAct(starting_page="https://www.makemytrip.com/", ...)
nova.page.goto(url)   # immediately, no wait
nova.page.wait_for_load_state("domcontentloaded")
```

**What happened:** The React app now loads correctly — the search form is populated with the right route/date. But the results area shows **"NETWORK PROBLEM — We are unable to connect to our systems from your device."**

**Diagnosis:** `NovaAct(starting_page=X)` starts navigation but does NOT block the `with` body from executing. So `nova.page.goto(url)` fires immediately, **interrupting the homepage load before it completes**. The homepage never writes its session cookies or auth tokens to the browser. When the React app then makes its AJAX call for flight data, MMT's API sees a cookieless request and blocks it.

**Fix applied:** Add `nova.page.wait_for_load_state("load")` BEFORE `nova.page.goto(url)` to ensure the homepage finishes loading (all scripts download + execute, cookies are set).

Why `"load"` and not `"networkidle"`: `"networkidle"` waits for 500ms of quiet network, which can hang indefinitely on pages with analytics polling. `"load"` fires on `window.onload`, which is sufficient for session cookie initialization.

---

## Attempt 4 — Homepage `wait_for_load_state("load")` + `goto(url)`

**Approach:**
```python
NovaAct(starting_page=homepage, ...)
nova.page.wait_for_load_state("load")   # wait for homepage to finish
nova.page.goto(url)
nova.page.wait_for_load_state("domcontentloaded")
```

Also updated the `wait` instruction to: *"If you see a NETWORK PROBLEM error, click REFRESH once, then wait for flights to appear. Do not click anything else."*

**What happened:** The NETWORK PROBLEM persists even after `wait_for_load_state("load")`. The model correctly clicked REFRESH once, but the error remained. The model then went rogue — it kept clicking REFRESH repeatedly, then started filling the search form, clicking SEARCH, and typing city names (all explicitly prohibited). It ran out of steps (max=30) before extraction could run.

**Diagnosis:** The NETWORK PROBLEM is **consistent** — clicking REFRESH 5+ times still shows the same error. This is not a race condition or missing cookies. It is **headless browser fingerprint detection at the API layer**. MMT's flight data API endpoint (the `fetch()` call made by the React app) checks:
1. **HTTP User-Agent**: Playwright's headless Chromium sends `"... HeadlessChrome ..."` — detectable by the API server.
2. **`navigator.webdriver`**: Playwright sets this JS property to `true` in headless mode. MMT's React app likely checks this value before or during the API call.

The "REFRESH click does nothing" behavior confirms the API request is being blocked, not just slow. Re-triggering the same blocked request produces the same blocked result.

The model going rogue is a secondary issue: the `wait` instruction said "Do not click anything else" but the model overrode this after REFRESH failed. The instruction needed an explicit hard budget.

**Fix applied:** Two changes:
1. **Fingerprint masking**: After `wait_for_load_state("load")` and before `goto(url)`, inject two layers of UA masking (see Attempt 5).
2. **Stricter wait instruction**: `"Finish this step after at most one REFRESH"` — gives the model an explicit one-action budget, preventing the rogue loop.

---

## Attempt 5 — Fingerprint masking (CURRENT STATE as of 2026-03-10 ~09:00)

**Approach:** After the homepage loads, register fingerprint masking before `goto(url)`:

```python
nova.page.wait_for_load_state("load")

_REAL_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
nova.page.context.set_extra_http_headers({"User-Agent": _REAL_UA})
nova.page.add_init_script(
    f"Object.defineProperty(navigator, 'userAgent', {{get: () => '{_REAL_UA}'}});"
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)

nova.page.goto(url)
nova.page.wait_for_load_state("domcontentloaded")
```

**Why this works:**

| Layer | What it blocks | Playwright API |
|-------|---------------|---------------|
| HTTP headers | `"HeadlessChrome"` in every request (incl. flight data `fetch()`) | `context.set_extra_http_headers({"User-Agent": ...})` |
| JS context — UA string | `navigator.userAgent` visible to React scripts | `page.add_init_script(...)` |
| JS context — webdriver flag | `navigator.webdriver = true` checked before API call | `page.add_init_script(...)` |

**Why `add_init_script` timing matters:** The script is registered BEFORE `goto(url)`. In Playwright, `add_init_script` runs in every new document context BEFORE any page scripts execute. So when the search page loads, MMT's React bundle sees `webdriver = undefined` and a real UA before it has a chance to check and abort.

**Wait instruction applied:**
```
Wait for the flight listings to fully load.
If you see a "NETWORK PROBLEM" error, click the REFRESH button exactly once,
then wait 3 seconds. After that single REFRESH attempt, finish this step.
Do NOT fill the search form. Do NOT click SEARCH.
Do NOT interact with anything else. Finish this step after at most one REFRESH.
```

**Actual result (confirmed by test run):**
- Wait step: model correctly clicks REFRESH once, sees "200-OK", waits 3 seconds, finishes ✅ (wait instruction worked)
- BUT: after REFRESH, the page shows **"200-OK"** (raw API JSON) — a NEW regression
- Extraction step: model is on "200-OK" page, completely lost, hallucinates URLs (DEL-HYD wrong date)

**Key finding from Attempt 5:** The UA masking CHANGED THE BEHAVIOR of the REFRESH click:
- Attempt 4 (no UA masking): REFRESH = React in-app retry (stays on NETWORK PROBLEM screen)
- Attempt 5 (UA masking active): REFRESH = full server reload → server serves raw API JSON with real UA → "200-OK"

This tells us MMT's server now treats the REFRESH request differently when it sees a real Chrome UA — it serves the raw API JSON response (200-OK) instead of the SPA HTML. This means clicking REFRESH is harmful when UA masking is active.

**Also confirmed:** NETWORK PROBLEM STILL APPEARED before REFRESH was clicked → UA + webdriver masking alone is not enough. MMT checks additional signals.

---

## Attempt 6 — Expanded stealth + REFRESH removed + page-drift guard (CURRENT)

**Changes applied:**

**1. Expanded `add_init_script`** — covers 4 signals instead of 2:
- `navigator.webdriver` → `undefined` (same as before)
- `navigator.userAgent` → real Chrome UA (same as before)
- `window.chrome` → realistic mock with `runtime`, `app`, `csi`, `loadTimes` — absent or incomplete in headless Chromium
- `navigator.plugins` → 5 named plugin entries — empty array in headless, populated in real Chrome
- `navigator.languages` → `['en-US', 'en']` — headless may send empty or single value

**2. Added `sec-ch-ua` Client Hint headers** to `set_extra_http_headers`:
- `sec-ch-ua: '"Google Chrome";v="122", "Not(A:Brand";v="24", "Chromium";v="122"'`
- `sec-ch-ua-mobile: "?0"` and `sec-ch-ua-platform: '"macOS"'`
- Without these, the `User-Agent` header says Chrome/122 but the Client Hints say something different — inconsistency detectable by bot scanners

**3. REFRESH removed from wait instruction:**
```
Wait up to 10 seconds for flight listings to appear on the page.
Do NOT click REFRESH. Do NOT fill the search form. Do NOT click SEARCH.
Do NOT interact with anything at all. Simply wait, then finish this step.
```
REFRESH with UA masking active causes navigation to "200-OK" — more damaging than NETWORK PROBLEM.

**4. Page-drift guard (Python code, after wait step):**
```python
if "itinerary=" not in nova.page.url:
    log.warning("MMT: page drifted after wait step (now: %s); restoring search page", nova.page.url)
    nova.page.goto(url)
    nova.page.wait_for_load_state("domcontentloaded")
```
Catches any URL drift (REFRESH click, model navigation, etc.) and restores the search page before extraction runs.

**Status:** Results from test confirmed NETWORK PROBLEM still appeared before REFRESH was clicked → Attempt 6 stealth alone is not enough. Akamai checks more than JS properties.

**Key diagnosis from expert review:** MMT uses **Akamai Bot Manager** specifically (not a generic WAF). Akamai's primary detection layers beyond JS fingerprints:
1. **`_abck` challenge cookie** — generated by Akamai's sensor JS that runs POST page-load via XHR. If you navigate away before the sensor finishes (~2-4s after `window.onload`), the browser arrives at the search page without `_abck`, and the flight data API returns 403/NETWORK PROBLEM unconditionally.
2. **Zero pointer events** — Akamai's sensor logs mouse/touch event timestamps. Sessions with no `mousemove`/`pointermove` events before the first navigation score as bot-like.
3. **Canvas determinism** — headless Chrome renders canvas identically across all instances (same `toDataURL()` hash), a strong collective fingerprint signal.
4. **Datacenter IP** — AWS Lambda/EC2 IP ranges are on Akamai's datacenter block list. This cannot be fixed in code (requires residential proxy).

---

## Attempt 7 — Akamai-specific: `_abck` warm-up + humanized interaction + extended fingerprint (CURRENT)

**Changes applied:**

**1. `_abck` warm-up dwell (highest impact):**
```python
nova.page.wait_for_load_state("load")
try:
    nova.page.wait_for_load_state("networkidle", timeout=6000)
except Exception:
    pass  # analytics polling may prevent networkidle — fall through
sleep(3)  # minimum dwell: Akamai sensor typically completes within 2-3s
```
- `networkidle` (500ms of quiet) ideally confirms Akamai's sensor XHRs have finished
- `sleep(3)` is a safety net — if networkidle hangs (analytics polling), the fixed wait still gives the sensor enough time to write `_abck`
- This is the most likely fix: the sensor was being interrupted before cookie write

**2. Humanized mouse movement:**
```python
nova.page.mouse.move(200, 300)
sleep(0.4)
nova.page.mouse.move(420, 360)
sleep(0.6)
```
- Two gentle `mousemove` events on the homepage before `goto(url)`
- Generates `mousemove`/`pointermove` DOM events that Akamai's sensor records
- Real user sessions always contain these; zero events = strong bot indicator

**3. Extended `add_init_script` — 10 signals total (was 5):**
| New signal | Headless default | Real Chrome value |
|-----------|-----------------|------------------|
| `navigator.hardwareConcurrency` | 1 | 8 (Mac) |
| `navigator.deviceMemory` | 0 / undefined | 8 |
| `window.outerWidth` | 0 (no browser UI) | screen.width |
| `window.outerHeight` | 0 (no browser UI) | screen.height |
| `screen.colorDepth` / `pixelDepth` | varies | 24 |
| `navigator.permissions.query('notifications')` | `'denied'` | `'default'` |
| `HTMLCanvasElement.prototype.toDataURL` | deterministic hash | per-session noise |

Canvas noise approach: a one-bit XOR flip on the top-left pixel before `toDataURL()`, immediately reverted — imperceptible to rendering but unique per session.

**Status (confirmed 2026-03-10 22:15):** ✅ **Phase 1 PASSED** — 7 real flights extracted, zero "NETWORK PROBLEM" errors. The Akamai `_abck` warm-up (networkidle+sleep3) was the decisive fix.

**New issue revealed — Phase 2 harvest:** The model found the cheapest flight (Air India Express IX 1464, ₹4998), clicked "View Prices", and got a "Getting More Fares..." popup that never finished loading — `ActExceededMaxStepsError` after 25 steps. Root cause is TBD: either the fare API is also bot-detected (same Akamai layer, different endpoint), or the popup requires a logged-in session to load fares. Phase 1 (search results) is fully working.

---

## Summary of the fix history

| Attempt | Code change | Symptom fixed | New symptom revealed |
|---------|------------|---------------|---------------------|
| 1 | Form filling | — | Bot detection blocks form interaction |
| 2 | Direct URL as `starting_page` | No form filling | `200-OK` — SPA API endpoint, not the UI |
| 3 | `starting_page=homepage` + immediate `goto(url)` | SPA loads, form populated | NETWORK PROBLEM — homepage load interrupted (race) |
| 4 | `wait_for_load_state("load")` before `goto(url)` | Cookies/session initialized | NETWORK PROBLEM still — webdriver + UA signals |
| 5 | UA masking + `webdriver=undefined` | REFRESH loop stopped (1-action budget) | REFRESH → "200-OK" regression; NETWORK PROBLEM still shown |
| 6 | `window.chrome` + `plugins` + `sec-ch-ua` + no REFRESH + drift guard | Page-drift fixed | NETWORK PROBLEM still — Akamai `_abck` cookie not warm |
| 7 | `_abck` warm-up (networkidle+sleep3) + mouse moves + hardwareConcurrency + canvas noise + permissions | **NETWORK PROBLEM FIXED** ✅ | Phase 2 harvest: "Getting More Fares..." popup stuck loading |

---

## Phase 2 harvest investigation — 2026-03-11

### What Phase 2 needed to do

After Phase 1 extracts flight listings, Phase 2 harvests the booking URL for the cheapest flight:
1. Find the flight card on the search results page
2. Click "View Prices" → MMT shows a fare comparison popup titled "Getting More Fares..."
3. Wait for the popup to resolve and show fare tiers (CLASSIC | VALUE | FARE BY MAKEMYTRIP | FLEX)
4. Click the first "BOOK NOW" button (CLASSIC = cheapest tier)
5. Land on the booking review page and capture its URL

The original implementation used `nova.act(book_then_continue.md)` — a Nova Act instruction asking the model to find, click, wait, and navigate.

### Why nova.act failed for Phase 2

The model called `wait("0")` in a tight loop — checking the popup state after zero real dwell. Since `wait("0")` costs exactly one Nova Act step, all 25 steps were consumed in < 1 second of real time. The "Getting More Fares..." popup requires 10–30 seconds for the fare API to respond, so the model never saw it resolve.

**First fix attempt (instruction-level):** Rewrote `book_then_continue.md` to use explicit `wait("15")` calls (2× = 30s of dwell, costing only 2 steps). Increased `max_steps: 25 → 35` to cover the wait budget.

**Result:** Model correctly waited 45s (3× `wait("15")`) but popup STILL showed "Getting More Fares..." — BOOK NOW buttons never appeared.

### Network diagnostic — 2026-03-11 07:41

Created `tests/test_mmt_fare_api_diagnostic.py` — a standalone script that:
- Boots MMT exactly like agent.py (Akamai warm-up + fingerprint masking + `goto(url)`)
- Attaches `page.on("request")` and `page.on("response")` listeners
- Clicks "View Prices" using **direct Playwright** (`page.locator("text=View Prices").first.click()`)
- Waits 35 seconds and logs all captured API traffic

**Key findings from the diagnostic:**

| Finding | Detail |
|---------|--------|
| Fare API endpoint | `GET https://flights-cb.makemytrip.com/api/fare-recomendations/stream?rKey=RKEY:15103cdf-af96-426a-ab08-00143a02695d:84_0&pax=A-1_C-0_I-0&crId=...` |
| Second Akamai challenge | `POST https://www.makemytrip.com/E3ikd27e0/fAgBZcO/...` with `sensor_data` body — fires **on click** of "View Prices", not on page load |
| SSE streaming | `fare-recomendations/stream` uses Server-Sent Events — `response.text()` blocks indefinitely on open stream, explaining 0 responses captured |
| Separate subdomain | `flights-cb.makemytrip.com` has its own Akamai policy, independent of `www.makemytrip.com` |

**Critical observation:** The user saw the diagnostic's headed browser load the popup **successfully** — BOOK NOW buttons appeared. The diagnostic used `page.locator("text=View Prices").first.click()` (direct Playwright), while the main agent used `nova.act()`. This was the decisive clue.

### Root cause of Phase 2 failure

Akamai fires a **per-click bot challenge** the moment "View Prices" is clicked:
- `POST /E3ikd27e0/fAgBZcO/...` with fresh `sensor_data` payload
- The challenge is evaluated by Akamai's edge against the browser's fingerprint at click time
- In the same warm session with fingerprint masking active, the browser passes the challenge automatically
- When `nova.act()` drives the click, the model's intermediate steps (snapshot-taking, scrolling, highlighting) generate additional browser activity that may alter the fingerprint between the homepage warm-up and the click moment
- Direct Playwright click fires the challenge cleanly in the same session state → passes → fare API responds → popup loads

---

## Phase 2 harvest fix — 2026-03-11 ✅

### Approach: hybrid Playwright + Nova Act

Replace `nova.act(book_then_continue.md)` with a new static method `_playwright_click_view_prices_and_book_now(page, airline, flight_number, price)` that uses direct Playwright calls for the click sequence, keeping Nova Act only for the extraction steps.

```python
@staticmethod
def _playwright_click_view_prices_and_book_now(page, airline, flight_number, price) -> bool:
    # Step 1: click "View Prices" on the target flight card
    # — tries card-scoped :has-text(flight_number) selectors first,
    #   falls back to first "text=View Prices" on page (safe for offers_top_n=1)

    # Step 2: wait for BOOK NOW button (up to 45s)
    page.wait_for_selector("text=BOOK NOW", timeout=45000, state="visible")

    # Step 3: click first BOOK NOW (CLASSIC = leftmost / cheapest tier)
    page.locator("text=BOOK NOW").first.click()

    # Step 4: wait for booking page DOM
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    sleep(2)
    return True
```

`_harvest_itinerary_urls()` calls this method instead of `nova.act()`. If it returns `False`, the harvest entry is skipped (logged as warning).

### Test result (2026-03-11 07:52–07:56)

```
Phase 1:  7 non-stop BOM→DEL flights extracted ✅
Filters:  "6 AM to 12 PM" applied (20471ms) ✅
Harvest:  IndiGo 6E 5263 ₹5000 — 12602ms
          BOOK NOW appeared in < 1s ✅
Offer:    fare_type=NON-REFUNDABLE
          base_fare=4500 taxes=1200 convenience_fee=0 total_fare=5700 ✅
```

### Architectural note on MMT booking URLs

Unlike Cleartrip (which returns a dedicated `/flights/review/...` URL after clicking Book), MMT's booking page is **React state-based** — after clicking BOOK NOW, `page.url` stays at the search URL. The `itinerary_url` captured in `_harvest_itinerary_urls()` is therefore the same as the search URL.

The Phase 5 extraction sessions (`_extract_coupon_offer_branch`) open a fresh Nova Act session at the search URL and navigate to the booking page internally (running the `book_then_continue` flow again via the model). This adds ~48s overhead per extraction session but correctly reaches the booking review page.

Future optimization: stay in the harvest session after clicking BOOK NOW and run fare + coupon extraction without opening a separate session.

---

## Summary of the fix history

| Attempt | Code change | Symptom fixed | New symptom revealed |
|---------|------------|---------------|---------------------|
| 1 | Form filling | — | Bot detection blocks form interaction |
| 2 | Direct URL as `starting_page` | No form filling | `200-OK` — SPA API endpoint, not the UI |
| 3 | `starting_page=homepage` + immediate `goto(url)` | SPA loads, form populated | NETWORK PROBLEM — homepage load interrupted (race) |
| 4 | `wait_for_load_state("load")` before `goto(url)` | Cookies/session initialized | NETWORK PROBLEM still — webdriver + UA signals |
| 5 | UA masking + `webdriver=undefined` | REFRESH loop stopped (1-action budget) | REFRESH → "200-OK" regression; NETWORK PROBLEM still shown |
| 6 | `window.chrome` + `plugins` + `sec-ch-ua` + no REFRESH + drift guard | Page-drift fixed | NETWORK PROBLEM still — Akamai `_abck` cookie not warm |
| 7 | `_abck` warm-up (networkidle+sleep3) + mouse moves + hardwareConcurrency + canvas noise + permissions | **Phase 1 NETWORK PROBLEM FIXED** ✅ | Phase 2 harvest: "Getting More Fares..." popup stuck loading |
| UI filters | `apply_filters` step + `_window_to_mmt_slot()` mapping | Time-slot filter buttons clicked ✅ | — |
| Phase 2 fix | `_playwright_click_view_prices_and_book_now()` replacing `nova.act(book_then_continue)` | **Phase 2 harvest FIXED** ✅ | Phase 5 extraction sessions open at search URL (~48s overhead) |

**Current status (2026-03-11): Full pipeline PASSING ✅**
- Phase 1: search extraction (7 non-stop flights)
- UI filters: time-slot button clicking
- Phase 2: harvest with direct Playwright click
- Phase 5: fare summary + coupon extraction (separate Nova Act session)
