# Ixigo Agent — Changelog 2026-03-11

## Bot Detection Hardening

The Ixigo agent was failing to extract flights because the browser was being detected as
a headless bot. Applied all six bot-detection countermeasures proven on the MakeMyTrip
agent (see [`docs/BOT_DETECTION_GUIDE.md`](../../../docs/BOT_DETECTION_GUIDE.md) for the
full reference).

### Previous state

- `starting_page` was the direct search URL (`/search/result/flight?...`)
- No UA masking, no JS fingerprint overrides, no sensor warm-up, no mouse interaction
- Extraction instruction told the model to "refresh the page ONCE" — dangerous in SPA context
- Only 3 city codes (Mumbai, Delhi, Bangalore)

### Changes applied

#### Layer 1 — SPA Routing Fix

`/search/result/flight?...` is a client-side route. Navigating to it as `starting_page`
can return raw JSON or an empty page because the React SPA has not bootstrapped.

**Fix:** `starting_page` is now the homepage (`https://www.ixigo.com/`). After the SPA
loads, the agent calls `nova.page.goto(search_url)` to trigger client-side routing.

#### Layer 2 — HTTP Header Overrides

Headless Chromium sends `HeadlessChrome` in the User-Agent on every HTTP request,
including background `fetch()` / XHR calls that load flight data.

**Fix:** `nova.page.context.set_extra_http_headers()` replaces the UA with a real
Chrome/122 string, and sets matching `sec-ch-ua`, `sec-ch-ua-mobile`, and
`sec-ch-ua-platform` Client Hint headers.

#### Layer 3 — JS Fingerprint Masking

Headless Chromium differs from real Chrome in many JS-readable properties. The agent
now registers an `add_init_script()` **before** navigating to the search URL. The script
overrides 10+ properties:

| Property | Headless value | Patched value |
|----------|---------------|---------------|
| `navigator.webdriver` | `true` | `undefined` |
| `navigator.userAgent` | `"...HeadlessChrome..."` | Real Chrome/122 |
| `window.chrome` | `undefined` | Realistic mock with `runtime`, `app` |
| `navigator.plugins` | `[]` | 5 named PDF plugin entries |
| `navigator.languages` | `["en-US"]` or `[]` | `["en-US", "en"]` |
| `navigator.hardwareConcurrency` | `1` | `8` |
| `navigator.deviceMemory` | `0` or `undefined` | `8` |
| `window.outerWidth/Height` | `0` | `screen.width / screen.height` |
| `screen.colorDepth` | varies | `24` |
| `navigator.permissions.query('notifications')` | `'denied'` | `'default'` |
| `HTMLCanvasElement.toDataURL()` | identical hash every session | per-session 1-bit noise |

#### Layer 4 — Cookie / Sensor Warm-up

Security sensors (Akamai, Cloudflare, PerimeterX, etc.) write challenge cookies via XHR
after `window.onload`. Navigating away before the sensor completes leaves the browser
without a valid session cookie.

**Fix:** After `wait_for_load_state("load")` on the homepage:
1. `wait_for_load_state("networkidle", timeout=6000)` — waits for all XHRs to settle
2. `sleep(3)` — minimum dwell to cover the sensor's typical 2-3s completion window

#### Layer 5 — Behavioral Signals

Real users move their mouse before clicking or navigating. A session with zero pointer
events is flagged as bot-like.

**Fix:** Two `mouse.move()` calls with natural pauses (0.4s, 0.6s) on the homepage
before navigating to the search URL.

#### Layer 6 — Page Drift Guard + Dedicated Wait Step

**Wait step:** Added a dedicated `wait` step in `config.yaml` that tells the model to
wait up to 10 seconds for flight listings to appear, with explicit instructions to NOT
click REFRESH, SEARCH, or interact with anything.

**Drift guard:** After the wait step, the agent checks `nova.page.url`. If the URL
no longer contains `search/result/flight`, it navigates back to the search URL.

**Extraction instruction:** Removed the "refresh the page ONCE" advice from
`wait_and_extract.md`. This was causing the same regression seen in MMT Attempt 5 —
a full-page server reload exits the SPA router and lands on a raw API response.

---

## URL-Level Filters (stops, departure time, arrival time)

Ixigo accepts filter parameters directly in the search URL. The agent now encodes
`max_stops`, `departure_window`, and `arrival_window` from the filters dict into URL
query parameters, so the page loads pre-filtered — no UI interaction needed.

### URL parameters

| Filter | URL param | Values |
|--------|-----------|--------|
| Sort order | `sort_type` | `cheapest` (default), `quickest`, `earliest`, `best` — from `filters.sort_by` (price/duration/departure) |
| Max stops | `stops` | Integer (e.g. `0` for non-stop, `1` for max 1 stop) |
| Departure time | `takeOff` | Comma-separated bucket values |
| Arrival time | `landing` | Comma-separated bucket values |

### Time bucket mapping

The `departure_window` and `arrival_window` filters are `["HH:MM", "HH:MM"]` ranges.
The agent maps them to Ixigo's time bucket values using overlap logic:

| Bucket | Time range | `ixigo_value` |
|--------|-----------|---------------|
| Early morning | 00:00 - 08:00 | `EARLY_MORNING` |
| Morning | 08:00 - 12:00 | `MORNING` |
| Afternoon | 12:00 - 16:00 | `AFTERNOON` |
| Evening | 16:00 - 20:00 | `EVENING` |
| Night | 20:00 - 24:00 | `NIGHT` |

A window `[lo, hi]` selects every bucket whose interval overlaps `[lo, hi]`. If all
buckets would be selected, no parameter is added (equivalent to no filter). Multiple
selected buckets are joined with commas.

**Example:** `filters={"departure_window": ["06:00", "12:00"], "max_stops": 0}` produces:

```
...&stops=0&takeOff=EARLY_MORNING,MORNING
```

### Benefit

Pre-filtering in the URL means:
- The page loads with only matching flights — fewer results for the model to scroll through
- Extraction is faster and more reliable
- No need for the model to interact with filter UI elements (which can trigger bot detection)

---

## Config Expansion

- Added `premium_economy` and `first` to `class_codes`
- Expanded `city_codes` from 3 to 26 cities (matching MakeMyTrip coverage)
- Added `time_buckets` configuration for departure/arrival window mapping
- Added `max_steps_default: 50`
- Tightened extraction schema: added `required` fields and `HH:MM` pattern validation

---

## Files Changed

| File | Change |
|------|--------|
| `agent.py` | SPA boot sequence, all 5 bot-detection layers, URL filter encoding, page drift guard |
| `config.yaml` | `time_buckets`, `wait` step, expanded city/class codes, tightened schema |
| `instructions/wait_and_extract.md` | Removed "refresh" instruction, added "Do NOT click REFRESH" guard |
| `docs/CHANGELOG_2026-03-11.md` | This file |
