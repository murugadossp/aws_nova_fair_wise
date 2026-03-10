# Browser Automation — Bot Detection Challenges

A practical guide to the detection layers that block headless browsers, with annotated
examples from the **MakeMyTrip (MMT) agent** — a real case study that went through
seven distinct attempts before succeeding.

---

## Table of Contents

1. [The detection stack — overview](#1-the-detection-stack--overview)
2. [Layer 1 — SPA Routing Traps](#2-layer-1--spa-routing-traps)
3. [Layer 2 — HTTP Headers](#3-layer-2--http-headers)
4. [Layer 3 — JavaScript Context Fingerprinting](#4-layer-3--javascript-context-fingerprinting)
5. [Layer 4 — Session Cookie Validation (Akamai `_abck`)](#5-layer-4--session-cookie-validation-akamai-_abck)
6. [Layer 5 — Behavioral / Event Signals](#6-layer-5--behavioral--event-signals)
7. [Layer 6 — Network / Platform (not fixable in code)](#7-layer-6--network--platform-not-fixable-in-code)
8. [Debugging methodology](#8-debugging-methodology)
9. [Summary — MMT fix history](#9-summary--mmt-fix-history)

---

## 1. The Detection Stack — Overview

Modern travel sites use **multi-layer bot detection**. Each layer is independently
sufficient to block a request — patching one layer while leaving another intact still
fails. The full stack on MMT (Akamai Bot Manager):

```
Request arrives at Akamai Edge
    │
    ├── Layer 2: HTTP headers           ← HeadlessChrome UA → block
    ├── Layer 4: _abck cookie           ← missing/invalid → block
    │
    (passes edge → reaches server → SPA loads → JS runs)
    │
    ├── Layer 1: SPA routing            ← cold-navigate API endpoint → "200-OK" JSON
    ├── Layer 3: JS context fingerprint ← webdriver=true, no plugins → React blocks API call
    ├── Layer 5: behavioral signals     ← zero mouse events → Akamai risk score ↑
    └── Layer 6: datacenter IP          ← AWS IP range → Akamai block (not fixable in code)
```

Each layer corresponds to a **distinct MMT failure mode** observed during testing.
The section for each layer shows: what the signal is, how MMT uses it, what the
symptom looked like, and the code fix applied.

---

## 2. Layer 1 — SPA Routing Traps

### What it is

Single-Page Applications (React, Vue, Angular) handle routing in the browser via
JavaScript. The server doesn't know about `/flight/search?itinerary=BOM-DEL-...` as
a page — it's just a hash or pushState route that the JavaScript router interprets
after the SPA bundle loads.

### How MMT uses it

`https://www.makemytrip.com/flight/search?itinerary=BOM-DEL-17/03/2026&...` is a
**client-side route**, not a server-side page. The server responds to a cold GET
request on this URL with a raw JSON API response (the internal flights data API),
not the SPA HTML.

### Symptom (Attempt 2)

```
Browser navigates to https://www.makemytrip.com/flight/search?itinerary=BOM-DEL-...
Page shows: "200-OK"        ← plain text, raw JSON — not the React app
Model sees an empty page, extraction returns nothing
```

### Fix — SPA boot sequence

Never cold-navigate to the search URL. Instead:
1. Start at the **homepage** (this bootstraps the React SPA)
2. Wait for the homepage to fully load
3. Navigate to the search URL — the JavaScript router is now alive and handles it

```python
# In agents/makemytrip/agent.py — search() method

homepage = _CONFIG["base_url"] + "/"          # https://www.makemytrip.com/
with NovaAct(starting_page=homepage, ...) as nova:
    nova.page.wait_for_load_state("load")     # SPA JS bundle is now loaded
    # ... fingerprint masking ...
    nova.page.goto(url)                        # client-side routing kicks in
    nova.page.wait_for_load_state("domcontentloaded")
```

### Key principle

> **Check whether a URL is a server-side page or a client-side route before navigating to it directly.**
> Signal: cold navigation returns JSON or `"200-OK"` plain text instead of HTML.

---

## 3. Layer 2 — HTTP Headers

### What it is

Every HTTP request — including the `fetch()` / XHR calls that the SPA's JavaScript
makes to load flight data — carries HTTP headers. Akamai's edge server inspects these
headers on every request.

### How MMT uses it

Two headers are checked:

| Header | Headless Chromium sends | Real Chrome sends | Consequence |
|--------|------------------------|-------------------|-------------|
| `User-Agent` | `...HeadlessChrome/122...` | `...Chrome/122...` | Akamai blocks "HeadlessChrome" |
| `sec-ch-ua` | omitted or mismatched | `"Google Chrome";v="122"...` | Inconsistency detectable |

Note: these headers appear on **every** HTTP request — including the background
`fetch()` the React app makes to the flights API, not just the initial page load.

### Symptom (Attempt 4)

```
React app loads correctly (form populated with BOM→DEL, 17 Mar)
Flight results area shows: "NETWORK PROBLEM — We are unable to connect..."
Clicking REFRESH 5+ times: same error every time  ← consistent = API-layer block
```

The consistency rules out race conditions or missing cookies. The API endpoint itself
is rejecting the request because it sees `HeadlessChrome` in the UA.

### Fix — context-level header override

```python
# In agents/makemytrip/agent.py

_REAL_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
nova.page.context.set_extra_http_headers({
    "User-Agent": _REAL_UA,
    # sec-ch-ua must match the User-Agent version — inconsistency is itself a signal
    "sec-ch-ua": '"Google Chrome";v="122", "Not(A:Brand";v="24", "Chromium";v="122"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
})
```

`context.set_extra_http_headers()` overrides headers for **all** HTTP requests in the
context — including the background `fetch()` calls made by React, not just the initial
page navigation.

### Key principle

> **UA masking must apply at the context level, not the page level**, so it covers
> background XHR/fetch calls made by JavaScript, not just the top-level navigation.

---

## 4. Layer 3 — JavaScript Context Fingerprinting

### What it is

JavaScript running inside the page can read browser properties to build a fingerprint.
Headless Chromium has several telltale differences from real Chrome that fingerprinting
scripts detect.

### How MMT uses it

MMT's React bundle checks multiple `navigator` and `window` properties before making
the flights API call. If the checks fail, it either doesn't make the call at all, or
sends a flag that causes the API to reject it.

### Detected properties and their headless values

| Property | Headless Chromium | Real Chrome | Detection type |
|----------|-------------------|-------------|----------------|
| `navigator.webdriver` | `true` | `undefined` | **Primary** — set by Playwright |
| `navigator.userAgent` | `"...HeadlessChrome..."` | `"...Chrome/122..."` | JS-visible string |
| `window.chrome` | `undefined` or incomplete | Full object with `runtime`, `app` | Missing object |
| `navigator.plugins` | `[]` (empty) | 3-5 named PDF plugins | Empty array |
| `navigator.languages` | `["en-US"]` or `[]` | `["en-US", "en"]` | Single/empty |
| `navigator.hardwareConcurrency` | `1` | `8` (Mac) | Unrealistic value |
| `navigator.deviceMemory` | `0` or `undefined` | `8` | Missing value |
| `window.outerWidth/Height` | `0` (no browser chrome) | `innerWidth/Height + UI` | Zero dimensions |
| `screen.colorDepth` | varies | `24` | Wrong value |
| `navigator.permissions.query('notifications')` | `'denied'` | `'default'` | No UI to prompt |
| `HTMLCanvasElement.toDataURL()` | identical hash every session | per-session noise | Deterministic output |

### Fix — `add_init_script` before navigation

The key timing constraint: the script must run **before** the page's own JavaScript.
`add_init_script` registers a script that executes at the very start of every new
document context — before any `<script>` tags, before React loads.

```python
# Registered BEFORE nova.page.goto(url) — applies to the search page document
nova.page.add_init_script(f"""
(function() {{
    // webdriver — primary Playwright/Selenium signal
    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});

    // userAgent — JS-visible string (separate from HTTP header)
    Object.defineProperty(navigator, 'userAgent', {{get: () => '{_REAL_UA}'}});

    // window.chrome — absent in headless Chromium
    if (!window.chrome) {{
        window.chrome = {{
            runtime: {{ id: undefined, connect: function(){{}}, sendMessage: function(){{}} }},
            app: {{}}, csi: function(){{}}, loadTimes: function(){{}}
        }};
    }}

    // navigator.plugins — empty array in headless
    Object.defineProperty(navigator, 'plugins', {{get: () => [
        {{name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: '...'}},
        {{name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
        // ... 3 more entries
    ]}});

    // navigator.languages — may be single-element or empty in headless
    Object.defineProperty(navigator, 'languages', {{get: () => ['en-US', 'en']}});

    // Hardware / memory — unrealistic defaults in headless
    Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => 8}});
    Object.defineProperty(navigator, 'deviceMemory',        {{get: () => 8}});

    // outerWidth/Height — 0 in headless (no browser UI chrome)
    try {{
        Object.defineProperty(window, 'outerWidth',  {{get: () => screen.width  || 1440}});
        Object.defineProperty(window, 'outerHeight', {{get: () => screen.height || 900}});
    }} catch(e) {{}}

    // screen color depth
    try {{
        Object.defineProperty(screen, 'colorDepth', {{get: () => 24}});
        Object.defineProperty(screen, 'pixelDepth',  {{get: () => 24}});
    }} catch(e) {{}}

    // Permissions — headless returns 'denied' (no UI to show prompts)
    try {{
        const _q = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = function(desc) {{
            if (desc && desc.name === 'notifications')
                return Promise.resolve({{ state: 'default', onchange: null }});
            return _q(desc);
        }};
    }} catch(e) {{}}

    // Canvas fingerprint noise — headless renders identically every session
    // (same toDataURL() hash = strong collective bot signal)
    try {{
        const _orig = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function() {{
            if (this.width > 0 && this.height > 0) {{
                const ctx = this.getContext('2d');
                if (ctx) {{
                    const p = ctx.getImageData(0, 0, 1, 1);
                    p.data[0] ^= 1;            // flip one low bit (imperceptible)
                    ctx.putImageData(p, 0, 0);
                    const res = _orig.apply(this, arguments);
                    p.data[0] ^= 1;            // restore immediately
                    ctx.putImageData(p, 0, 0);
                    return res;
                }}
            }}
            return _orig.apply(this, arguments);
        }};
    }} catch(e) {{}}
}})();
""")
```

### Why timing matters

`add_init_script` vs injecting after navigation:

```
add_init_script (registered before goto):
    Page starts loading → [OUR SCRIPT RUNS] → React scripts execute → React sees webdriver=undefined ✅

inject via evaluate() after goto:
    Page starts loading → React scripts execute → [React checks webdriver=true, aborts API call] → [OUR SCRIPT RUNS] ✗
```

### Key principle

> **Override JS properties with `add_init_script` before navigating**, not after.
> The fingerprint check happens during React's initialization, before any user
> interaction — you must win the race by injecting before the page scripts start.

---

## 5. Layer 4 — Session Cookie Validation (Akamai `_abck`)

### What it is

Akamai Bot Manager issues a **challenge cookie** (`_abck`) by running a JavaScript
sensor after the page loads. The sensor collects browser fingerprints and sends them
to Akamai's edge via an XHR POST. Akamai validates the data and writes the `_abck`
cookie. All subsequent API requests from that browser session are validated against
this cookie.

### Timeline of the sensor

```
window.onload fires
    │
    ├─ (0ms)   Akamai sensor JS starts executing
    ├─ (500ms) Sensor collects: canvas hash, plugin list, timing data, event data
    ├─ (1-2s)  Sensor sends XHR POST to https://www.makemytrip.com/akam/13/...
    ├─ (2-4s)  Akamai edge validates fingerprint, writes _abck cookie
    └─ (>4s)   _abck is available — flight data API will now accept requests
```

### How MMT uses it

MMT's flight data API endpoint checks for a valid `_abck` cookie on every request.
If the cookie is missing or invalid, it returns the "NETWORK PROBLEM" error — not a
generic 403, but a React UI error that looks like a connectivity issue.

### Symptom (Attempts 3, 4, 5, 6)

```
Homepage loads correctly
goto(url) navigates to search page
React renders, form is populated, route/date correct
BUT: "NETWORK PROBLEM — We are unable to connect to our systems from your device."

Clicking REFRESH: same error (not transient — consistent = API-layer rejection)
```

This was misdiagnosed as webdriver/UA detection (Attempts 4 and 5) until the expert
review identified Akamai specifically. The actual root cause: the browser navigated
to the search URL *before* the `_abck` sensor XHR completed on the homepage.

### Why Attempts 4-6 partially worked but still failed

```
Attempt 4: wait_for_load_state("load") → enough for cookies, but NOT for _abck XHR
    "load" fires on window.onload — the sensor starts here but isn't done yet.

Attempt 5: added webdriver + UA masking → JS and HTTP layers fixed
    But _abck still not written (navigated away 50ms after "load")

Attempt 6: added chrome/plugins/sec-ch-ua — more JS signals covered
    But _abck still not written — timing problem persists
```

### Fix — Akamai warm-up dwell

```python
# agents/makemytrip/agent.py — after wait_for_load_state("load")

# Wait for Akamai's sensor XHR to complete and write the _abck cookie.
# networkidle (500ms quiet) is the ideal signal — all XHRs done.
# Fall back to a fixed sleep if networkidle times out (analytics polling).
try:
    nova.page.wait_for_load_state("networkidle", timeout=6000)
except Exception:
    pass  # analytics polling can prevent networkidle indefinitely
sleep(3)  # minimum dwell — Akamai sensor typically completes within 2-3s
```

Why `networkidle` with fallback `sleep`:
- `networkidle` fires when there are 0 in-flight connections for 500ms — ideal confirmation that the sensor XHR completed
- BUT: analytics scripts (GA, Hotjar, etc.) make periodic polling requests, preventing `networkidle` from ever firing on busy pages
- The `except + sleep(3)` ensures we always wait at least 3 seconds even if `networkidle` times out

### Result

This was the **decisive fix**. After adding the 3-second dwell, the NETWORK PROBLEM
error disappeared entirely — 7 real flights extracted on the very first run.

### Key principle

> **`window.onload` is not the end of page initialization.** Third-party security
> scripts (Akamai, Cloudflare, DataDome) execute *after* `onload` and need additional
> time to complete their challenge handshake. Always add a dwell after `load` before
> navigating away from the landing page.

---

## 6. Layer 5 — Behavioral / Event Signals

### What it is

Real users move their mouse before clicking. Akamai's sensor records the presence
(or absence) of pointer events — `mousemove`, `pointermove`, `mouseenter` — during
the session. A session with **zero mouse events** from page open to navigation
scores as bot-like.

### How MMT uses it

Akamai's risk scorer weights sessions with no mouse interaction as higher-risk. Even
with a valid `_abck` cookie, a suspiciously clean session (no movement, immediate
navigation) can trigger a re-challenge or soft block on subsequent requests.

### Fix — humanized interaction before navigation

```python
# agents/makemytrip/agent.py — after add_init_script, before goto(url)

# Two gentle mouse moves generate mousemove/pointermove DOM events.
# Pauses between moves mimic natural human hand movement.
try:
    nova.page.mouse.move(200, 300)   # move to a neutral area of the homepage
    sleep(0.4)
    nova.page.mouse.move(420, 360)   # move again — slightly different position
    sleep(0.6)
except Exception:
    pass  # non-fatal
```

### Key principle

> **Generate interaction events before navigation.** Even minimal mouse movement
> (2 moves, ~1 second) is enough to populate Akamai's event timeline and avoid
> a zero-event bot signature.

---

## 7. Layer 6 — Network / Platform (Not Fixable in Code)

These signals cannot be patched via JavaScript or Playwright APIs. They require
infrastructure-level changes.

### Datacenter IP ranges

Akamai maintains block lists of known datacenter IP ranges (AWS EC2, Lambda, GCP,
Azure). Requests from these ranges are immediately flagged as automation.

**Symptom:** Even with a perfect JS fingerprint and valid `_abck` cookie, requests
from an AWS IP range may still trigger "NETWORK PROBLEM" or a 403 in production.

**Fix:** Route automation traffic through residential proxies (ISP-assigned IPs),
or use a scraping provider that maintains residential IP pools.

### TLS / JA3 Fingerprinting

The TLS ClientHello message — sent by the browser before any HTTP headers — contains
cipher suite ordering, extension ordering, and other parameters set at the Chromium
binary level. Playwright's bundled Chromium has a different TLS fingerprint than
real Chrome.

**Symptom:** Indistinguishable from other bot signals at the UI level; typically
manifests as a block before the page even loads.

**Fix:** Cannot be changed via `add_init_script`. Requires a patched Chromium binary
(e.g., `playwright-stealth` patches) or a TLS-transparent proxy.

### Canvas / WebGL (if JS patching is insufficient)

Even with `toDataURL()` noise injection, WebGL fingerprinting (via `getParameter`,
`readPixels`) may still return headless-specific values.

**Fix:** `playwright-stealth` Python package covers WebGL and canvas comprehensively:

```python
from playwright_stealth import stealth_sync
stealth_sync(nova.page)   # after wait_for_load_state("load")
```

---

## 8. Debugging Methodology

### How to diagnose which layer is blocking

| Symptom | Most likely layer |
|---------|------------------|
| Page shows `"200-OK"` plain text | Layer 1 — SPA routing trap |
| "NETWORK PROBLEM" that persists after REFRESH | Layer 2 (HTTP UA) or Layer 4 (`_abck`) |
| "NETWORK PROBLEM" even after UA masking | Layer 4 (`_abck` warm-up missing) |
| Login popup appears and blocks flow | Layer 3 (JS fingerprint) or Layer 6 (IP) |
| Empty results / spinner that never loads | Layer 3 or Layer 5 (behavioral) |
| Immediate 403 before any page loads | Layer 6 (datacenter IP or TLS) |

### Is the error transient or consistent?

- **Consistent** (same error after 5+ REFRESH clicks) → API-layer block (Layer 2 or 4)
- **Transient** (disappears after 1-2 retries) → race condition or network issue

### Model `think()` traces as ground truth

Nova Act's `think()` traces show exactly what the model *saw* on screen — use these
to confirm what page state exists, not what you expect:

```
think("I am on the flights results page... I can see the flight listings on the page")
→ Layer 1, 2, 4, 5 all passed: page rendered correctly

think("I see a NETWORK PROBLEM error message")
→ React rendered but flight API call failed: Layer 2 or 4

think("I see a '200-OK' text on the page")
→ Layer 1 trap: cold-navigated to API endpoint, SPA not loaded
```

---

## 9. Summary — MMT Fix History

| Attempt | Fix applied | Layer addressed | Symptom fixed | New symptom |
|---------|------------|-----------------|---------------|-------------|
| 1 | Form filling via `search_form.md` | — | — | Bot detection blocks form interaction |
| 2 | Direct URL as `starting_page` | — | No form filling | `"200-OK"` — SPA API endpoint |
| 3 | `starting_page=homepage` + immediate `goto(url)` | Layer 1 | SPA loads, form populated | NETWORK PROBLEM — homepage race |
| 4 | `wait_for_load_state("load")` before `goto(url)` | Layer 1 (race) | Cookies/session initialized | NETWORK PROBLEM still — UA + webdriver |
| 5 | UA masking + `webdriver=undefined` | Layer 2 + Layer 3 (partial) | REFRESH loop stopped | REFRESH → `"200-OK"` regression |
| 6 | `window.chrome` + `plugins` + `sec-ch-ua` + no REFRESH + drift guard | Layer 3 (expanded) + model control | Page-drift fixed | NETWORK PROBLEM still — `_abck` not warm |
| **7** | `_abck` warm-up (networkidle+sleep3) + mouse moves + 10 JS signals | **Layer 4 + Layer 5 + Layer 3** | **NETWORK PROBLEM FIXED ✅** | Phase 2 fare popup (separate issue) |

### The complete working sequence (MMT, as of Mar 10 2026)

```python
# 1. Layer 1 fix: boot the SPA at the homepage
homepage = "https://www.makemytrip.com/"
with NovaAct(starting_page=homepage, ...) as nova:

    # 2. Layer 1 fix: wait for homepage scripts to execute
    nova.page.wait_for_load_state("load")

    # 3. Layer 4 fix: give Akamai's _abck sensor time to complete
    try:
        nova.page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    sleep(3)

    # 4. Layer 2 fix: replace HeadlessChrome UA on all HTTP requests
    nova.page.context.set_extra_http_headers({
        "User-Agent": REAL_UA,
        "sec-ch-ua": '"Google Chrome";v="122"...',
        ...
    })

    # 5. Layer 3 fix: override JS fingerprint properties before page scripts run
    nova.page.add_init_script("""
        navigator.webdriver → undefined
        navigator.userAgent → real UA
        window.chrome → realistic mock
        navigator.plugins → 5 entries
        navigator.languages → ['en-US', 'en']
        navigator.hardwareConcurrency → 8
        navigator.deviceMemory → 8
        window.outerWidth/Height → screen dimensions
        screen.colorDepth → 24
        navigator.permissions → 'default' for notifications
        HTMLCanvasElement.toDataURL → per-session 1-bit noise
    """)

    # 6. Layer 5 fix: generate mouse events before navigation
    nova.page.mouse.move(200, 300); sleep(0.4)
    nova.page.mouse.move(420, 360); sleep(0.6)

    # 7. Layer 1 fix: navigate via client-side routing
    nova.page.goto(search_url)
    nova.page.wait_for_load_state("domcontentloaded")
```

> **Key insight:** The `_abck` warm-up (`sleep(3)`) was the decisive fix.
> All JS property patches were necessary scaffolding, but the flight data API
> blocked requests regardless of fingerprint quality until the `_abck` cookie
> was properly initialized. The ordering matters: warm-up must happen **before**
> fingerprint masking and navigation.
