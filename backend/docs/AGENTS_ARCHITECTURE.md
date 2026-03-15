# Agents — Folder Structure and Architecture

This document describes how the FareWise Nova Act agents are organized: per-agent packages, config-driven prompts and schemas, and how they are used by the orchestrator and tests.

---

## Folder layout

Each agent lives in its own **package** under `backend/agents/`:

```
backend/agents/
├── __init__.py              # Re-exports all agent classes (optional convenience)
├── act_handler.py           # Shared exception handler; used by travel agents
├── orchestrator.py          # TravelOrchestrator, ProductOrchestrator
├── ixigo/
│   ├── __init__.py          # from .agent import IxigoAgent; __all__ = ["IxigoAgent"]
│   ├── agent.py             # IxigoAgent class; loads config, runs Nova Act
│   └── config.yaml          # workflow_name, base_url, class_codes, city_codes, steps
├── cleartrip/
│   ├── __init__.py          # from .agent import CleartripAgent; __all__ = ["CleartripAgent"]
│   ├── agent.py             # CleartripAgent class; loads config, runs Nova Act
│   └── config.yaml          # workflow_name, base_url, steps (instructions + schemas)
├── makemytrip/
│   ├── __init__.py
│   ├── agent.py
│   ├── config.yaml
│   ├── docs/
│   │   └── DEBUG_BOT_DETECTION_2026-03-10.md   # full bot detection debug history
│   └── instructions/
│       ├── extractor_prompt.md      # main extraction (popup dismissal + STRICT RULES)
│       ├── book_then_continue.md
│       ├── search_form.md           # kept for reference; NOT in execution path
│       └── ...
├── goibibo/
│   ├── __init__.py
│   ├── agent.py
│   └── config.yaml          # kept in codebase; not in default travel agent set
├── amazon/
│   ├── __init__.py
│   ├── agent.py
│   └── config.yaml
└── flipkart/
    ├── __init__.py
    ├── agent.py
    └── config.yaml
```

- **`agent.py`** — Contains the agent class (e.g. `CleartripAgent`). It loads `config.yaml` from the same directory, builds URLs, runs the Nova Act workflow, and normalizes results. Search logic and exception handling stay here; on failure, travel agents delegate to `ActExceptionHandler.handle()`.
- **`config.yaml`** — Holds all prompt text (instructions) and JSON schemas for `nova.act()` so that copy and schema changes do not require code edits. Supports placeholders such as `{{criteria}}`, `{{base_url}}`, `{{max_results}}`.
- **`__init__.py`** — Exposes the agent class so that `from agents.cleartrip import CleartripAgent` (and similar) works. No agent logic lives here.

Imports elsewhere (orchestrator, main, tests) use the package: `from agents.ixigo import IxigoAgent`, `from agents.cleartrip import CleartripAgent`, `from agents.makemytrip import MakeMyTripAgent`, etc. The test runner `tests/run_agent.sh` invokes test scripts by name (e.g. `test_cleartrip_agent.py`); it does not depend on the agents folder structure.

---

## config.yaml structure

Each agent’s `config.yaml` is loaded at module import time from the directory containing `agent.py` (e.g. `Path(__file__).resolve().parent / "config.yaml"`). No shared config loader is used; each agent is self-contained.

### Common keys

| Key | Description |
|-----|-------------|
| `workflow_name` | Nova Act workflow name (e.g. `farewise-cleartrip`). Can be overridden by env var (e.g. `NOVA_ACT_WORKFLOW_CLEARTRIP`). |
| `base_url` | Site base URL; used for building search URLs and for the `{{base_url}}` placeholder in instructions. |

### Travel agents (Ixigo, Cleartrip, MakeMyTrip, Goibibo)

Additional keys:

| Key | Description |
|-----|-------------|
| `city_codes` | Map of city name (lowercase) to IATA/code (e.g. `mumbai: BOM`). Used for URL construction. |
| `max_steps_default` | Default `max_steps` for `nova.act()`; can be overridden by `NOVA_ACT_MAX_STEPS`. |
| `class_codes` | Map of travel class to URL cabin code. Used by Ixigo (`?class=`) and MakeMyTrip (`&cabinClass=`). Cleartrip uses a separate `class_codes` key that maps to full words (`Economy`, `Business`). |

> **Note:** `default_criteria` has been removed. Search criteria are now built at runtime from the structured `filters` dict via the `_filters_to_criteria(filters)` static method on each agent class. If `filters` is `None`, the method returns `"top 5 cheapest flights sorted by price ascending"`.

**Steps:**

- **`wait`** — Single instruction run once before extraction to let the results page fully load. Can be inline (`instruction`) or from a file (`instruction_file`).
- **`extraction`** — Instruction and `schema` (JSON Schema for the flight array). Cleartrip uses a **two-layer prompt**: `site_adapter_file` (stable Cleartrip UI knowledge) + `extractor_file` (task prompt). MakeMyTrip uses a single file (`instruction_file: instructions/extractor_prompt.md`) with a self-contained prompt that also handles popup dismissal. The extraction schema uses `required` + `additionalProperties: false` to enforce strict field validation.
- **Offers** (Cleartrip + MakeMyTrip) — When `fetch_offers=True`, after extraction the agent harvests itinerary URLs then runs parallel offer extraction (fare summary first, then coupons). Returns `{ "flights", "offers_analysis" }`. Each `offers_analysis` entry includes `fare_breakdown` (base_fare, taxes, convenience_fee, total_fare), `fare_type`, and `coupons`.
  - **Cleartrip:** harvest uses `nova.act(book_then_continue)` to click Book → captures a real `/flights/review/...` URL. Extraction sessions open that URL directly.
  - **MakeMyTrip:** harvest uses `_playwright_click_view_prices_and_book_now()` — a direct Playwright method (not `nova.act`) that clicks "View Prices" → waits for BOOK NOW popup → clicks first BOOK NOW. MMT's booking page is React state-based: `page.url` stays at the search URL after clicking. Extraction sessions therefore open at the search URL and navigate to the booking page internally.

**Direct URL approach (Cleartrip):**

Cleartrip builds a direct search results URL and passes it as `starting_page` to `NovaAct` — no form-filling step is needed. The `_build_search_url()` helper constructs the URL from IATA codes (via `city_codes` map), a formatted date, and a cabin class code.

- **Cleartrip URL format:** `/flights/results?from={FROM}&to={TO}&depart_date={DD}/{MM}/{YYYY}&adults=1&...&class={Economy|Business}`

**SPA boot sequence (MakeMyTrip):**

MakeMyTrip is a React Single-Page Application. The search URL format is:
```
/flight/search?itinerary={FROM}-{TO}-{DD}/{MM}/{YYYY}&tripType=O&paxType=A-1_C-0_I-0&intl=false&cabinClass={E|B|P|F}&lang=eng
```

However, `/flight/search?...` is a **server-side API endpoint** — cold-navigating to it returns a JSON/plain-text "200-OK" response, not the web UI. The route is only handled by the React router after the SPA JavaScript bundle has been loaded from the homepage.

The MMT agent uses this boot sequence (order is critical):
1. `NovaAct(starting_page=homepage)` — loads the homepage, bootstrapping the SPA JS bundle
2. `nova.page.wait_for_load_state("load")` — waits for the homepage to fully load (session cookies written)
3. **Akamai `_abck` warm-up** — `wait_for_load_state("networkidle", timeout=6000)` + `sleep(3)`: Akamai's sensor JS runs POST-`window.onload` and writes the `_abck` challenge cookie via XHR over 2–4s; navigating before it completes causes NETWORK PROBLEM on the flight data API
4. **Fingerprint masking** — 10 signals via `add_init_script` + `set_extra_http_headers` (see below)
5. **Humanized mouse movement** — two `mouse.move()` calls on the homepage; Akamai logs pointer events and scores sessions with zero events as bot-like
6. `nova.page.goto(url)` — triggers client-side routing to the search results page
7. `nova.page.wait_for_load_state("domcontentloaded")`

Note: `user_data_dir=tmp_dir` (fresh profile per run) was tested but dropped — Nova Act's `launch_persistent_context` requires a pre-existing "Local State" file; a blank `tempfile.TemporaryDirectory()` lacks this.

**Headless fingerprint masking (MakeMyTrip — 10 signals):**

MMT uses Akamai Bot Manager. The agent masks 10 signals across HTTP and JS layers:

| Layer | Signal | Playwright API |
|-------|--------|---------------|
| HTTP | `User-Agent` (replaces `HeadlessChrome`) | `set_extra_http_headers` |
| HTTP | `sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform` Client Hints | `set_extra_http_headers` |
| JS | `navigator.webdriver` → `undefined` | `add_init_script` |
| JS | `navigator.userAgent` → real Chrome/122 UA | `add_init_script` |
| JS | `window.chrome` → realistic mock (runtime, app, csi, loadTimes) | `add_init_script` |
| JS | `navigator.plugins` → 5 named PDF plugin entries | `add_init_script` |
| JS | `navigator.languages` → `['en-US', 'en']` | `add_init_script` |
| JS | `navigator.hardwareConcurrency` → 8 | `add_init_script` |
| JS | `navigator.deviceMemory` → 8 | `add_init_script` |
| JS | `window.outerWidth/outerHeight`, `screen.colorDepth/pixelDepth` | `add_init_script` |
| JS | `navigator.permissions.query('notifications')` → `'default'` | `add_init_script` |
| JS | `HTMLCanvasElement.toDataURL` → 1-bit per-session noise | `add_init_script` |

**MakeMyTrip Phase 2 harvest — direct Playwright approach:**

After Phase 1 extraction, Phase 2 clicks "View Prices" on the cheapest flight to reach the booking page. MMT fires a **per-click Akamai bot challenge** at `flights-cb.makemytrip.com` (a separate subdomain with its own Akamai policy) the moment "View Prices" is clicked. The fare popup ("Getting More Fares...") resolves only when this challenge passes.

Using `nova.act()` for this click caused `ActExceededMaxStepsError` because the model looped `wait("0")` — checking the popup state with zero real dwell, exhausting the step budget before the fare API could respond. Using direct Playwright `page.locator().click()` passes the challenge cleanly in the same warm session.

The harvest method `_playwright_click_view_prices_and_book_now(page, airline, flight_number, price)`:
1. Clicks "View Prices" using Playwright locators (card-scoped `:has-text(flight_number)`, fallback to first on page)
2. `page.wait_for_selector("text=BOOK NOW", timeout=45000)` — popup resolves typically in < 1s
3. Clicks first BOOK NOW (CLASSIC / cheapest tier)
4. Waits for booking page DOM

**Note:** MMT's booking page URL is not separately addressable — `page.url` stays at the search URL after clicking BOOK NOW (React state-based routing). Phase 5 extraction sessions open at the search URL and navigate to the booking page internally.

For the complete bot-detection debug history, see [`agents/makemytrip/docs/DEBUG_BOT_DETECTION_2026-03-10.md`](../agents/makemytrip/docs/DEBUG_BOT_DETECTION_2026-03-10.md).

### Two-layer extraction (Cleartrip)

Cleartrip uses a site adapter + extractor prompt:

- **`site_adapter_cleartrip.md`** — Stable Cleartrip page structure (flight cards, what to ignore, booking link rules, data format). Rarely changes.
- **`extractor_prompt.md`** — Small task prompt with `{{criteria}}` and `{{base_url}}`: extract matching flights, return JSON array, interaction rules (extract when 3+ visible; do not click links or sort; read href only).

The agent builds the extraction instruction as `site_adapter_content + "\n\n" + extractor_content`, then substitutes placeholders. This keeps prompt size down and improves maintainability. See [instructions/site_adapter_cleartrip.md](../agents/cleartrip/instructions/site_adapter_cleartrip.md) and [instructions/extractor_prompt.md](../agents/cleartrip/instructions/extractor_prompt.md).

### Product agents (Amazon, Flipkart)

- **`steps.extraction`** — `instruction` (placeholders `{{max_results}}`, `{{base_url}}`) and `schema` for the product array.
- **`steps.pre`** (optional, e.g. Flipkart) — One instruction run before extraction (e.g. close login popup). No schema.

### Placeholders

Instructions in `config.yaml` can use placeholders filled in by the agent at runtime:

- `{{criteria}}` — Human-readable search hint built by `_filters_to_criteria(filters: dict)` from the structured `filters` dict passed by the orchestrator. Example output: `"departure between 06:00 and 11:59; non-stop flights only; sort by departure ascending"`. Never a raw user string.
- `{{base_url}}` — From config `base_url`.
- `{{max_results}}` — Number of results to extract (product agents).

The agent uses a simple replace (e.g. `instruction.replace("{{criteria}}", criteria)`) so the exact placeholder names must match the keys passed from code.

### Schema format

Schemas in YAML match JSON Schema. For nullable types use a list with the string `"null"` (e.g. `type: [integer, "null"]`) so that the value is the string `"null"` for JSON Schema and not YAML’s `null`. Example:

```yaml
original_price: { type: [integer, "null"] }
```

**Where schema is used:** The schema is read from config and passed once per step to `nova.act(instruction, schema=...)`. The Nova Act SDK uses it to constrain the model’s output and to return a parsed structure (e.g. `ActGetResult.parsed_response` as a list or dict). No need to define the same structure elsewhere.

**Pattern: schema in config.yaml (no double engineering).** We keep instructions and schema together in each agent’s `config.yaml`. That way there is a single place to edit prompts and response shape per step, and the agent simply loads and passes the schema through to `nova.act()`. No separate schema file or duplicate definition is required.

**Alternative: Pydantic.** Some codebases use Pydantic models as the single source of truth and derive the schema in code (e.g. `YourModel.model_json_schema()`) before calling `nova.act(..., schema=...)`. That gives type safety and reuse across the app but moves schema into Python instead of config. For FareWise we use the config-driven pattern above so that non-code config (YAML) holds both instructions and schemas.

---

## Agent class pattern

1. **Load config once** at module level: `_CONFIG = yaml.safe_load(open(Path(__file__).parent / "config.yaml"))`.
2. **Resolve backend root** for imports: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))` so that `logger`, `nova_auth`, and `agents.act_handler` can be imported.
3. **`_filters_to_criteria(filters: dict | None) -> str`** — static method on every travel agent. Converts the structured `filters` dict from the orchestrator into a readable criteria hint for the Nova Act prompt. Falls back to `"top 5 cheapest flights sorted by price ascending"` when `filters` is `None`. Example:
   ```python
   @staticmethod
   def _filters_to_criteria(filters: dict | None) -> str:
       if not filters:
           return "top 5 cheapest flights sorted by price ascending"
       parts = []
       dep_window = filters.get("departure_window")
       if dep_window and len(dep_window) == 2:
           parts.append(f"departure between {dep_window[0]} and {dep_window[1]}")
       if filters.get("max_stops") == 0:
           parts.append("non-stop flights only")
       sort_by = filters.get("sort_by", "price")
       parts.append(f"sort by {sort_by} ascending")
       return "; ".join(parts)
   ```
4. **`search(from_city, to_city, date, travel_class="economy", filters=None)`** — uniform signature across all travel agents. `filters` is the structured dict from the orchestrator (or `None` for default behavior).
5. **In `search()`:**
   - Pop `NOVA_ACT_API_KEY` from env (IAM mode; key conflicts with IAM credentials).
   - Call `get_or_create_workflow_definition(workflow_name)` from `nova_auth`.
   - Build URL, call `_filters_to_criteria(filters)` to get `criteria` string.
   - Run `Workflow` + `NovaAct` context managers.
   - For each step: get `instruction` and `schema` from `_CONFIG["steps"][...]`, substitute `{{criteria}}` / `{{base_url}}`, call `nova.act(instruction, schema=..., max_steps=...)`.
   - Parse result: if `nova.act()` returns `ActGetResult`, use `parsed_response`; otherwise treat as list.
   - Normalize results: prepend `base_url` to relative URLs; then run **URL date correction**: if the extracted URL contains a 4-digit year that does not match the search date year (e.g. model returns 2024 for a 2026 search), replace that year in the URL so the link opens the correct date. The Cleartrip agent implements this in `_fix_url_date_if_wrong(url, search_date)` and applies it to each flight URL before appending to results (and in the `ActInvalidModelGenerationError` recovery path).
   - On exception: call `ActExceptionHandler.handle(e, "AgentName", context)` and return `[]`.

All travel agents always return a **list** of flight dicts. Each dict contains at minimum: `platform`, `from_city`, `to_city`, `date`, `class`, `airline`, `flight_number`, `departure`, `arrival`, `duration`, `stops`, `price`, `url`.

---

## Shared components

- **`agents/act_handler.py`** — `ActExceptionHandler.handle(exc, agent_name, context)`. Used by Cleartrip, MakeMyTrip, and Ixigo to log and return `[]` on Nova Act or other errors. See [EXCEPTION_HANDLING.md](EXCEPTION_HANDLING.md).
- **`nova_auth.py`** — `get_or_create_workflow_definition(name)`. Checks if a Nova Act workflow definition exists in AWS and creates it if not. In-memory cache avoids repeat AWS API calls within the same process. Called at the start of every `search()` in IAM mode.
- **`agents/orchestrator.py`** — `TravelOrchestrator` reads `plan["route"]` and `plan["filters"]` from the planner output, dispatches to agents in parallel via `ThreadPoolExecutor`, collects results, then passes the combined list and `filters` to `FlightNormalizer`. All agents return a flat `list[dict]`.
- **`nova/flight_normalizer.py`** — `FlightNormalizer.normalize(flights, filters)`. Pure Python: dedup by `(airline, flight_number, departure)`, apply `filters["max_stops"]`, apply `filters["departure_window"]`, sort by `filters["sort_by"]`. No model call.
- **`nova/reasoner.py`** — `NovaReasoner.calculate_best_flight(flights, selected_cards)`. Two-step: (A) Python pre-ranking via `_baseline_price()` + `_build_all_results()` assigns deterministic ranks 1..N; (B) LLM receives only rank-1 flight + its platform's card offers and returns best card benefit. See [FLIGHT_DATA_FLOW.md](../FLIGHT_DATA_FLOW.md#4-final-reasoning-nova-pro--python-pre-ranking--card-benefit).

---

## Nova Act error handling patterns

### `_act_with_retry()` — ActInvalidModelGenerationError recovery

`ActInvalidModelGenerationError` is raised when Nova Act generates a zero-height bounding box for a click target (e.g., `<box>389,756,414,756</box>`). Root cause: a popup appears mid-step and obscures the intended element, causing the model to target the overlay instead.

**Pattern (implement in each agent's `agent.py`):**

```python
from nova_act import ActInvalidModelGenerationError

def _act_with_retry(nova, instruction: str, *, max_retries: int = 1, **kwargs):
    for attempt in range(max_retries + 1):
        try:
            return nova.act(instruction, **kwargs)
        except ActInvalidModelGenerationError as e:
            if attempt >= max_retries:
                raise
            log.warning(
                "ActInvalidModelGenerationError (attempt %d/%d) — dismissing popups and retrying: %s",
                attempt + 1, max_retries + 1, e,
            )
            _playwright_dismiss_popups(nova)
            sleep(1)
```

Replace every `nova.act(...)` call inside extraction and offer loops with `_act_with_retry(nova, ...)`. The `**kwargs` pass-through preserves `schema=`, `max_steps=`, and other arguments unchanged.

**Reference implementation:** `agents/ixigo/agent.py` — all `nova.act()` calls inside `_do_extraction()`, `book_then_continue`, and `extract_coupons_from_booking_page` use `_act_with_retry`.

---

## Phase 3 patterns

### book_url deduplication (prevents session collision)

Two flights from the same airline can share an identical `book_url` on the search results page (e.g., both point to the same Ixigo booking URL). When dispatched in parallel, both sessions navigate to the same page — one flight target is never analyzed, and the second slot's fare data actually belongs to the first slot.

**Pattern — apply before `asyncio.gather()` in `_run_offer_loop_parallel()`:**

```python
seen_urls: set[str] = set()
targets = [dict(t) for t in targets]          # shallow copy — don't mutate caller's list
for t in targets:
    bu = (t.get("book_url") or t.get("booking_url") or "").strip()
    if bu:
        if bu in seen_urls:
            log.warning(
                "Duplicate book_url for %s %s — clearing to force search-page navigation",
                t.get("airline", "?"), t.get("flight_number", "?"),
            )
            t.pop("book_url", None)
            t.pop("booking_url", None)
        else:
            seen_urls.add(bu)
```

When a target has no `book_url`, the agent falls back to navigating to the search page and locating the flight by airline/flight_number. This is slower but produces correct results.

**Reference implementation:** `agents/ixigo/agent.py` — `_run_offer_loop_parallel()`.

---

## IndiGo flight number rules

IndiGo operates both **3-digit** (e.g., 6E189, 6E796) and **4-digit** (e.g., 6E6081) flight numbers. Only flight numbers with ≤2 digits after `6E` are definitively OCR truncation noise.

**In `FlightNormalizer._normalize_flight_number()`:**
- `len(digits) <= 2` → log WARNING (OCR noise)
- `len(digits) == 3` → valid scheduled flight, no warning
- `len(digits) == 4` → standard IndiGo 4-digit, no warning
- `len(digits) > 4` → trim to 4 digits

**In session analysis (`prompts/session_analysis_prompt.md`):**
- CHECK-5 only flags ≤2 digits. 3-digit IndiGo numbers are noted as valid and marked ✅.
- Deduction guide: OCR penalty only for confirmed ≤2-digit truncation, never for 3-digit numbers.

---

## Agent tests and validation

Agent tests (e.g. `tests/test_cleartrip_agent.py`) assert not only that the agent returns flights and sets `platform`, but also **schema and correctness**:

- **Required fields:** Each flight has `airline`, `flight_number`, `departure`, `arrival`, `duration`, `stops`, `price`, `url` (see `REQUIRED_FLIGHT_FIELDS` in the test).
- **Types:** `price` and `stops` are integers.
- **Times:** `departure` and `arrival` are in `HH:MM` (5 characters, contain `:`).
- **URL:** Starts with the agent’s base URL (e.g. `https://www.cleartrip.com`); URL should contain the search year (catches wrong-year URLs if date correction is skipped or fails).

The test helper `validate_flight_schema(flights, search_date)` centralizes these checks. New travel agent tests should call an equivalent validator so regressions in schema or extraction are caught early. See [tests/test_cleartrip_agent.py](../tests/test_cleartrip_agent.py) for the pattern (`REQUIRED_FLIGHT_FIELDS`, `validate_flight_schema`, `CLEARTRIP_BASE_URL`).

---

## Adding a new travel agent

> **Reference implementation:** Use `agents/ixigo/agent.py` as the canonical template — it has the most complete and up-to-date implementation including `_act_with_retry`, book_url deduplication, `_playwright_dismiss_popups`, and the full Phase 3 parallel offer loop.

1. Create a package under `agents/`, e.g. `agents/newsite/`.
2. Add **`config.yaml`** with `workflow_name`, `base_url`, `city_codes`, `max_steps_default`, and `steps` (at least `wait` + `extraction` with `instruction_file` and `schema`). Add `class_codes` if the site's URL uses a cabin-class code parameter (like Ixigo, MakeMyTrip). Use `required` + `additionalProperties: false` in extraction schema for strict validation.
3. Add **`agent.py`** with:
   - `_filters_to_criteria(filters: dict | None) -> str` static method (copy pattern from IxigoAgent)
   - `search(from_city, to_city, date, travel_class=”economy”, filters=None)` signature
   - Pop `NOVA_ACT_API_KEY`, call `get_or_create_workflow_definition(workflow_name)`, run `Workflow`/`NovaAct`
   - **`_act_with_retry(nova, instruction, *, max_retries=1, **kwargs)`** — module-level helper (copy from Ixigo); use this instead of bare `nova.act()` everywhere
   - **`_playwright_dismiss_popups(nova)`** — dismisses overlays before retry; copy from Ixigo
   - **book_url deduplication** — in `_run_offer_loop_parallel()`, clear duplicate `book_url` before parallel dispatch (see [Phase 3 patterns](#phase-3-patterns) above)
   - On exception: `return ActExceptionHandler.handle(e, “NewSite”, context)`
4. Add **`__init__.py`** with `from .agent import NewSiteAgent` and `__all__ = [“NewSiteAgent”]`.
5. Add the agent key to `_TRAVEL_AGENTS` in `agents/orchestrator.py`.
6. Add a test file `tests/test_newsite_agent.py` (copy pattern from `test_ixigo_agent.py`) and call `validate_flight_schema` (or an equivalent validator) on the returned flights so schema and URL checks are enforced.

No changes to a central “config loader” are required; each agent reads its own `config.yaml` from its package directory.

### Phase 3 offer loop checklist (for new agents)

| # | Requirement | Why |
|---|-------------|-----|
| 1 | `targets = filtered[:offers_top_n]` | Cap parallel sessions |
| 2 | book_url dedup before `asyncio.gather()` | Prevent same-page collision (CHECK-7b) |
| 3 | Use `_act_with_retry` for all `nova.act()` | Recover from `ActInvalidModelGenerationError` popup interference |
| 4 | Log `”Offers [N/N]: N coupons extracted”` on success | Session analysis prompt maps these to flights |
| 5 | Log `”Offers [N/N]: failed for ...”` on failure | Session analysis tracks failure rate |
| 6 | Return `offers.best_price_after_coupon` | Used by `NovaReasoner._baseline_price()` for accurate ranking |
