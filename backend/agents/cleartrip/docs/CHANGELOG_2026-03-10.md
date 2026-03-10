# FareWise — Changelog 2026-03-10

## Cleartrip agent

### `extract_fare_summary_booking.md`

Added `fare_type` to the extraction prompt so the itinerary page's selected fare name (e.g. "Regular" for IndiGo, "Value" for Air India Express) is captured in the same `act()` call that already extracts the fare breakdown — zero extra steps, zero latency cost.

```markdown
- fare_type: the selected fare name exactly as shown on the page (e.g. "Regular", "Value", "Smart", "Saver"); look for it near the flight info, fare breakdown, or itinerary header; omit this key entirely if not visible
```

### `config.yaml` — `extract_fare_summary_booking` schema

Added `fare_type: { type: string }` to the schema properties (optional — not in `required`). `additionalProperties: false` was already present, so the field had to be explicitly declared.

### `config.yaml` — global keys

Added `collect_convenience_fee: true`, `convenience_fee_probe_index: 0`, `reuse_probe_convenience_fee: true` at top level (previously these were only in MMT config; Cleartrip uses them via `_apply_convenience_fee_from_first`).

---

## MakeMyTrip agent — iterative rework (3 phases)

> For the full debug history with symptom-by-symptom analysis, see:
> [`agents/makemytrip/docs/DEBUG_BOT_DETECTION_2026-03-10.md`](../../agents/makemytrip/docs/DEBUG_BOT_DETECTION_2026-03-10.md)

### Phase 1 — Direct URL + strict extraction schema

**Problem:** The previous approach opened the MMT homepage and used `search_form.md` to fill in origin/destination/date. Bot detection blocks this: login popups, JS challenges, and interactive form events all trigger fingerprinting.

**Fix: skip the form, build a direct search URL**

New helper `_build_search_url()`:
```
https://www.makemytrip.com/flight/search
  ?itinerary={FROM}-{TO}-{DD}/{MM}/{YYYY}
  &tripType=O&paxType=A-1_C-0_I-0&intl=false
  &cabinClass={E|B|P|F}&lang=eng
```
- Date format: `DD/MM/YYYY` (parsed from YYYY-MM-DD input)
- Cabin codes via `class_codes` in config: `E`=Economy, `B`=Business, `P`=PremiumEconomy, `F`=First
- `search_form` step removed from the execution path (file kept for reference)

New `instructions/extractor_prompt.md`: popup dismissal, scroll-and-capture up to 7 flights, STRICT RULES (no hallucinated flights).

Schema tightened: `required` + `additionalProperties: false`, removed unreliable `url` field, enforces `HH:MM` pattern on `departure`/`arrival`.

**New symptom revealed:** Navigating directly to the search URL returns `"200-OK"` as plain text — it is a server-side API endpoint, not a web page. The React SPA only handles `/flight/search` as a client-side route after its JS bundle has been loaded.

---

### Phase 2 — SPA boot sequence (homepage → `wait_for_load_state` → `goto(url)`)

**Problem:** The direct URL is a React client-side route — it only renders when the SPA JavaScript router is already running.

**Fix: boot the SPA at the homepage, then navigate programmatically**

```python
homepage = _CONFIG["base_url"] + "/"
NovaAct(starting_page=homepage, ...)
nova.page.wait_for_load_state("load")   # wait for homepage scripts to run + cookies to be set
nova.page.goto(url)                      # triggers client-side routing
nova.page.wait_for_load_state("domcontentloaded")
```

`"load"` is used (not `"networkidle"`) because `"networkidle"` can hang indefinitely on pages with analytics polling; `"load"` (= `window.onload`) is sufficient for session cookie initialization.

Note: `user_data_dir=tmp_dir` was dropped. Nova Act's `launch_persistent_context` requires a pre-existing "Local State" file in the profile directory, which a fresh `tempfile.TemporaryDirectory()` does not have.

**New symptom revealed:** React app loads, search form is populated correctly, but flight results show **"NETWORK PROBLEM — We are unable to connect to our systems from your device."** even after multiple REFRESH clicks. Consistent error = not a race condition or missing cookies. It is headless browser fingerprint detection at the API layer.

---

### Phase 3 — Headless fingerprint masking (CURRENT, pending verification)

**Problem:** MMT's flight data API detects headless Chromium via two signals:
1. `"HeadlessChrome"` in the HTTP User-Agent sent with every `fetch()` request
2. `navigator.webdriver = true` set by Playwright in the JS context, checked by MMT's React code before making the API call

**Fix: mask both signals before navigating to the search URL**

```python
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
```

`add_init_script` is registered BEFORE `goto(url)` so it runs inside the search page document before any React scripts execute.

Wait instruction updated to hard-limit model recovery actions: `"Finish this step after at most one REFRESH"` — prevents rogue loop where model kept clicking REFRESH then filled the search form.

---

### Files changed (all three phases combined)

| File | Change |
|------|--------|
| `agents/makemytrip/agent.py` | `_build_search_url()`, SPA boot sequence, fingerprint masking, `wait_for_load_state("load")` |
| `agents/makemytrip/config.yaml` | `class_codes`, tightened extraction schema, updated `wait` instruction |
| `agents/makemytrip/instructions/extractor_prompt.md` | **New** — self-contained extraction with popup handling + STRICT RULES |
| `agents/makemytrip/docs/DEBUG_BOT_DETECTION_2026-03-10.md` | **New** — full debug history |
| `agents/cleartrip/instructions/extract_fare_summary_booking.md` | Added `fare_type` extraction |
| `agents/cleartrip/config.yaml` | Added global `collect_convenience_fee` keys |
| `docs/AGENTS_ARCHITECTURE.md` | Updated MMT section |
