# FareWise — Testing Guide

## Changelog

### 2026-03-15 — Initial test suite: Ixigo E2E

- 7 tests covering Phases 1–4 + session logging infrastructure
- Routes: Chennai → Bengaluru (primary), Mumbai → Delhi (secondary normalization)
- Travel date: 2026-03-22 (one week from 2026-03-15, ensuring live availability)
- `backend/run_test.sh` launcher added with suite, phase, and headed mode flags
- `tests/run_all_tests.py` extended with `--ixigo-e2e`, `--phase1-only`, `--headed` support

---

## 1. Overview

### Purpose

FareWise tests replicate real user interactions end-to-end — a real browser is launched via Nova Act, a real OTA website is navigated, and real flight data is extracted. Tests do not mock agents, do not stub HTTP calls, and do not use pre-recorded fixtures.

This means:

- A passing test proves the full pipeline works against a live website today.
- A failing test means something either broke in the code or the OTA changed its UI.
- Tests are inherently slower than unit tests (60–300s per test) and require AWS credentials.

### Test philosophy

Every test mimics a specific moment in the user journey:

| User action | Pipeline stage | Test |
|---|---|---|
| Enters route, clicks Search | Phase 1: extraction | `test_phase1_extraction` |
| Sees sorted flight list | Phase 2: normalization | `test_phase1_with_normalization` |
| Checks "Non-stop only" filter | Phase 2: filter validation | `test_phase1_with_filters` |
| Clicks Book on top flight | Phase 3: coupon/fare extraction | `test_phase3_offer_extraction` |
| Frontend shows interim cards while loading | Progress callback events | `test_on_progress_callbacks` |
| Full WebSocket search from extension | Full orchestrator pipeline | `test_full_orchestrator_pipeline` |
| Admin reviews a search in the dashboard | Session logging / audit trail | `test_session_logging` |

### What is NOT mocked

- **IxigoAgent** — uses a real Nova Act Workflow, opens a real Chromium browser
- **FlightNormalizer** — runs against real extracted data (no fixture input)
- **TravelOrchestrator** — the WebSocket layer is replaced with `_MockWebSocket` (a lightweight `send_json` capturer) but every agent and Nova model call is real
- **Nova Bedrock calls** — Nova Lite (planner), Nova Pro (reasoner) — all real API calls

### Current coverage

| Area | Tests | Status |
|---|---|---|
| Ixigo Phase 1 (extraction) | 3 tests | Active |
| Ixigo Phase 2 (normalization + filters) | 2 tests | Active |
| Ixigo Phase 3 (fare breakdown + coupons) | 2 tests | Active |
| Full WebSocket orchestrator pipeline | 1 test | Active |
| Session logging infrastructure | 1 test | Active |
| Nova Lite — identifier | separate file | Active |
| Nova Pro — reasoner | separate file | Active |
| Nova Multimodal — validator | separate file | Active |
| Cleartrip E2E | planned | Not yet written |
| MakeMyTrip E2E | planned | Not yet written |

---

## 2. Test Suite Structure

```
backend/
├── run_test.sh                    ← environment setup + test launcher (this is your entry point)
├── tests/
│   ├── test_ixigo_e2e.py          ← Ixigo end-to-end: 7 tests covering Phases 1–4 + logging
│   ├── run_all_tests.py           ← central test runner (delegates to individual test files)
│   ├── test_ixigo_agent.py        ← original Ixigo integration test (single search run)
│   ├── test_nova_identifier.py    ← Nova Lite: product identification from text/image
│   ├── test_nova_reasoner.py      ← Nova Pro: effective price calculation with card offers
│   ├── test_nova_validator.py     ← Nova Multimodal: image embedding cosine similarity
│   ├── test_nova_planner.py       ← TravelPlanner: NL query → structured route + filters
│   ├── test_cleartrip_agent.py    ← Cleartrip: Phase 1 + 2 + 3
│   ├── test_cleartrip_itinerary.py← Cleartrip: single itinerary booking page probe
│   ├── test_makemytrip_agent.py   ← MakeMyTrip: Phase 1 + 2 + 3
│   ├── test_makemytrip_itinerary.py← MakeMyTrip: single itinerary booking page probe
│   ├── test_amazon_agent.py       ← Amazon India: product search
│   ├── test_flipkart_agent.py     ← Flipkart: product search
│   ├── test_goibibo_agent.py      ← Goibibo: flight search (legacy)
│   ├── test_mmt_fare_api_diagnostic.py ← MMT fare API diagnostics
│   ├── run_agent.sh               ← per-agent shell runner (for manual testing)
│   ├── AGENT_RESPONSE_SCHEMA.md   ← canonical field reference
│   ├── AGENTS_ARCHITECTURE.md     ← agent folder layout, config.yaml
│   ├── BOT_DETECTION_GUIDE.md     ← anti-bot patterns and mitigations
│   └── EXCEPTION_HANDLING.md     ← Nova Act error handling guide
└── docs/
    ├── TESTING.md                 ← this file
    ├── AGENTS_ARCHITECTURE.md
    ├── EXCEPTION_HANDLING.md
    ├── BOT_DETECTION_GUIDE.md
    └── AGENT_RESPONSE_SCHEMA.md
```

The main distinction between `test_ixigo_agent.py` and `test_ixigo_e2e.py` is scope:

- `test_ixigo_agent.py` — a single search run with hardcoded flags (`RUN_PHASE_1`, `RUN_PHASE_3`). Good for manual debugging.
- `test_ixigo_e2e.py` — 7 independent test functions with structured assertions, skip logic, and a summary. The authoritative correctness check.

---

## 3. User Journey — What Each Test Mimics

### Test 1: `test_phase1_extraction`

**User action:** User enters "Chennai → Bengaluru, 2026-03-22, Economy" and clicks Search.

**What it simulates:** The backend `IxigoAgent.search(fetch_offers=False)` call. Nova Act opens `ixigo.com`, builds the search URL with the route encoded, waits for results to load, then extracts the raw flight list.

**Validates:**
- Return type is `list`
- Every flight has all `REQUIRED_RAW_FIELDS`: `airline`, `flight_number`, `departure`, `arrival`, `duration`, `stops`, `price`
- `price` is `int > 0`
- `stops` is `int`
- `departure` and `arrival` match `HH:MM` format (24h, 5-char string, `:` at position 2)
- `platform` field equals `"ixigo"` on every record

**Expected duration:** 60–90 seconds (one browser session, Phase 1 only)

**Phases covered:** Phase 1

**Notes:** If Ixigo shows "No Flights Found" for the route (e.g., dates too far out), the test treats 0 flights as a pass — the pipeline ran successfully even without results.

---

### Test 2: `test_phase1_with_normalization`

**User action:** User enters "Mumbai → Delhi, 2026-03-22, Economy" with default sort (by price).

**What it simulates:** Phase 1 extraction followed by `FlightNormalizer.normalize()`. The secondary route (Mumbai → Delhi) is used here specifically because it is a high-traffic corridor where normalization + deduplication have real data to work with.

**Validates:**
- Raw `IxigoAgent.search()` returns a non-empty list
- `FlightNormalizer.normalize(filters={"sort_by": "price"})` returns between 1 and 5 flights
- Every normalized flight has all `CANONICAL_FLIGHT_FIELDS`: `platform`, `airline`, `flight_number`, `departure`, `arrival`, `duration`, `stops`, `price`, `from_city`, `to_city`, `date`, `travel_class`
- `price` is `int > 0` on every canonical record
- Flights are sorted ascending by `price` (no two adjacent flights where `flights[i].price < flights[i-1].price`)
- No two flights share the same `(airline, flight_number)` pair (deduplication worked)
- Every normalized flight has `platform == "ixigo"`

**Expected duration:** 60–90 seconds (one browser session)

**Phases covered:** Phase 1, Phase 2

---

### Test 3: `test_phase1_with_filters`

**User action:** User checks "Non-stop only" (Sub-test A) and sets departure time to "06:00–12:00" (Sub-test B).

**What it simulates:** Two sub-tests that validate filter propagation through both the IxigoAgent URL-builder (which bakes filters into the Ixigo search URL as query params) and the FlightNormalizer (which re-validates and drops non-conforming results after extraction).

**Sub-test A — non-stop filter (`max_stops=0`):**
- Passes `filters={"max_stops": 0, "sort_by": "price"}` to `IxigoAgent.search()`
- After normalization, asserts every flight has `stops == 0`

**Sub-test B — departure window filter (`departure_window: ["06:00", "12:00"]`):**
- Passes `filters={"departure_window": ["06:00", "12:00"], "sort_by": "price"}` to `IxigoAgent.search()`
- After normalization, converts each `departure` string to minutes-since-midnight via `_parse_hhmm()`
- Asserts every departure falls within `[360, 720]` minutes (06:00 to 12:00)

**Validates:**
- Both agent calls return `list`
- Stops assertion: `flight["stops"] == 0` for all flights in non-stop results
- Time assertion: `360 <= _parse_hhmm(flight["departure"]) <= 720` for all flights in window results
- Returns early with PASS if 0 flights (filter may have excluded everything)

**Expected duration:** 90–150 seconds (two browser sessions)

**Phases covered:** Phase 1, Phase 2

---

### Test 4: `test_phase3_offer_extraction`

**User action:** User sees the cheapest Chennai → Bengaluru flight and clicks "Book" to see the full fare breakdown and available coupons.

**What it simulates:** `IxigoAgent.search(fetch_offers=True)` — Phase 1 (extraction) in the same browser session followed immediately by Phase 3 (offer/coupon extraction). Nova Act clicks "Book" for the top-N flights, navigates to the Ixigo booking page, and scrapes base fare, taxes, convenience fee, and coupon codes.

**Validates:**

Return value schema:
- `result` is `dict` (not `list` — `fetch_offers=True` changes the return type)
- `result["flights"]` — raw Phase 1 extraction list
- `result["offers_analysis"]` — list of per-flight offer dicts
- `result["filtered"]` — normalized + deduplicated flights

Per-offer assertions (`REQUIRED_OFFER_FIELDS`):
- `flight_number` — present
- `airline` — present
- `original_price` — `int > 0`
- `fare_details` — dict (may be empty if booking page failed, triggers `log.warning` but not failure)
- `coupons` — `list` (may be empty; Ixigo doesn't always show coupons)

When `fare_details` is populated:
- `fare_details["base_fare"]` — `int > 0`

When `coupons` is non-empty:
- `best_price_after_coupon` — `int >= 0`
- `best_price_after_coupon == min(c["price_after_coupon"] for c in coupons)` (the cheapest coupon is always selected)

**Expected duration:** 120–180 seconds (opens multiple booking pages in parallel)

**Phases covered:** Phase 1, Phase 3

---

### Test 5: `test_on_progress_callbacks`

**User action:** The FareWise extension frontend opens a WebSocket and listens for interim updates while the backend is running. Flight cards appear progressively while Phase 3 is still running.

**What it simulates:** The `on_progress` callback that `IxigoAgent.search()` fires during execution. The frontend relies on these callbacks to render interim cards (`"phase2_start"`) and update them with fare data as it arrives (`"offer_extracted"`).

**Validates:**

Callback events captured via a closure:
- At least 1 `"phase2_start"` event fired
- `"phase2_start"` data is a non-empty `list` of flights
- Every flight in `"phase2_start"` has: `airline`, `flight_number`, `departure`, `arrival`, `price`
- Zero or more `"offer_extracted"` events fired (one per booking page visited)
- Every `"offer_extracted"` data is a `dict` with: `flight_number`, `airline`, `original_price`

**Expected duration:** 120–180 seconds (same as Phase 3)

**Phases covered:** Phase 1, Phase 2 (interim), Phase 3

---

### Test 6: `test_full_orchestrator_pipeline`

**User action:** User opens the FareWise Chrome extension, enters "Chennai → Bengaluru, 2026-03-22, Economy" with no credit cards, and clicks Search. The full pipeline runs including TravelPlanner, all agents, FlightNormalizer, and NovaReasoner.

**What it simulates:** A real WebSocket search as triggered by the frontend. A `_MockWebSocket` replaces the live FastAPI WebSocket — it records every `send_json()` call made by `TravelOrchestrator.run()`. The orchestrator runs completely: Nova Lite plans the search, IxigoAgent extracts and fetches offers, FlightNormalizer normalizes, and NovaReasoner picks a winner.

**Validates:**

WebSocket message sequence:
- At least 1 `"agent_start"` message, with `agent == "ixigo"` in the list
- At least 1 `"coupon_analysis_scope"` message:
  - `flight_ids` is a `list`
  - `count` is `int > 0`
- Exactly 1 `"results"` message:
  - `winner` is present and non-null
  - `winner["price_effective"]` is `int > 0`
  - `with_coupons` is a non-empty `list`
- Exactly 1 `"done"` message, which must be the **last** message in the sequence

**Early exit (no flights):** If the orchestrator returns a `"No flights found"` error message, the test passes with a warning. This handles the case where Ixigo shows no results for the route/date.

**Expected duration:** 180–300 seconds (full pipeline: extraction + offers + Nova Pro reasoning)

**Phases covered:** Phase 1, Phase 2, Phase 3, Phase 4 (Nova Pro reasoning)

---

### Test 7: `test_session_logging`

**User action:** Admin opens the FareWise dashboard at `http://localhost:7891/admin` to review a past search.

**What it simulates:** The `SessionLogger` lifecycle that runs alongside every real search. This test does NOT open a browser — it validates that the logging infrastructure creates the correct directory structure and file contents.

**Validates:**

Session creation:
- `SessionLogger.create_session()` returns a non-empty string session ID
- Directory `logs/<today>/<session_id>/` is created

`metadata.json`:
- `session_id` matches
- `search_params.from_city == "Chennai"`
- `search_params.to_city == "Bengaluru"`
- `search_params.travel_date == "2026-03-22"`
- `search_params.travel_class == "economy"`
- `"ixigo"` appears in `search_params.agents`
- `status == "in_progress"` immediately after creation

`nova_act_session.log`:
- File exists
- File is non-empty (the root logger file handler was attached)

After `log_phase()`:
- `execution.json` is created and is a non-empty list
- Last entry has `phase == "test_phase"`, `agent == "ixigo"`, `status == "success"`

After `finalize_session()`:
- `metadata.json` updated with `status == "completed"`
- `"timestamp_end"` key present
- `"summary"` key present and is a `dict`

**Expected duration:** 1–3 seconds (no browser, no network calls)

**Phases covered:** Session lifecycle (runs alongside all phases in production)

---

## 4. Running Tests

### Quick reference

```bash
# Navigate to the backend directory first
cd /path/to/backend/

# Fast smoke test — Phase 1 only, no booking funnel (~3-4 min)
./run_test.sh ixigo --phase1-only

# Full Ixigo E2E suite — all 7 tests (~8-10 min)
./run_test.sh ixigo

# Watch what Nova Act is doing in the browser
./run_test.sh ixigo --headed

# Skip the slowest test (full orchestrator, ~3-5 min) but run everything else
./run_test.sh ixigo --skip-orchestrator

# Nova model tests only (no browser required, ~30-60s)
./run_test.sh nova

# Run all test groups (CI / pre-push)
./run_test.sh
```

### Direct Python invocation

If you prefer to run tests without the shell wrapper (e.g., inside a debugger or IDE):

```bash
cd backend/
source .venv/bin/activate

# Ixigo E2E full suite
python tests/test_ixigo_e2e.py

# Phase 1 only (skip Phase 3 + orchestrator)
python tests/test_ixigo_e2e.py --phase1-only

# Skip orchestrator only
python tests/test_ixigo_e2e.py --skip-orchestrator

# Show browser (Nova Act headed mode)
FAREWISE_HEADED=1 python tests/test_ixigo_e2e.py

# Nova model tests
python tests/test_nova_identifier.py
python tests/test_nova_reasoner.py
python tests/test_nova_validator.py

# All tests via the central runner
python tests/run_all_tests.py
python tests/run_all_tests.py --nova-only
python tests/run_all_tests.py --ixigo-e2e
python tests/run_all_tests.py --ixigo-e2e --phase1-only
```

### Via `run_all_tests.py` flags

```bash
python tests/run_all_tests.py              # nova models + agent tests + ixigo e2e (phase1 fast path)
python tests/run_all_tests.py --nova-only  # Nova models only, no browser
python tests/run_all_tests.py --agents-only# individual agent tests (amazon, flipkart, mmt, etc.)
python tests/run_all_tests.py --ixigo-e2e # Ixigo E2E full suite
python tests/run_all_tests.py --ixigo-e2e --phase1-only  # Ixigo Phase 1 only
python tests/run_all_tests.py --headed    # any of the above + FAREWISE_HEADED=1
```

### Via `tests/run_agent.sh` (manual per-agent runs)

For single-agent manual debugging, the `run_agent.sh` runner is convenient:

```bash
# From the backend/ directory:
./tests/run_agent.sh ixigo            # IxigoAgent P1+P2+P3
./tests/run_agent.sh cleartrip        # CleartripAgent
./tests/run_agent.sh nova             # Nova model tests (identifier + validator + reasoner + planner)
./tests/run_agent.sh all              # everything (~6-9 min)
```

---

## 5. Test Configuration

All configuration constants are defined at the top of `tests/test_ixigo_e2e.py`:

### `TRAVEL_DATE = "2026-03-22"`

Fixed to one week after the authoring date (2026-03-15). Choosing a date one week out gives high confidence of live inventory — flights are available and priced, unlike dates months out that may have sparse availability on some routes.

Do not use `date.today()` for the travel date — the test output must be reproducible with a known date, and a rolling date makes debugging sessions harder to compare.

### Routes

```python
ROUTE_FROM  = "Chennai"     # MAA — primary route origin
ROUTE_TO    = "Bengaluru"   # BLR — primary route destination
ROUTE2_FROM = "Mumbai"      # BOM — secondary route (normalization test only)
ROUTE2_TO   = "Delhi"       # DEL — secondary route destination
```

Chennai → Bengaluru is the primary route because it is:
- A short, high-frequency domestic corridor (15–20 flights/day)
- Reliably indexed on ixigo.com with full coupon data
- Non-stop options always available, making the `max_stops=0` filter testable

Mumbai → Delhi is the secondary route used only in `test_phase1_with_normalization` because it has even more flights, making deduplication and the 5-flight cap meaningful to validate.

### `TRAVEL_CLASS = "economy"`

Always economy. Business class tests would require a separate suite (prices, availability, and the booking funnel differ substantially).

### `CANONICAL_FLIGHT_FIELDS`

The complete set of fields every normalized flight (post-Phase 2) must have:

```python
CANONICAL_FLIGHT_FIELDS = (
    "platform",       # "ixigo" — which OTA the data came from
    "airline",        # e.g. "IndiGo", "Air India"
    "flight_number",  # e.g. "6E-537"
    "departure",      # "HH:MM" 24h string
    "arrival",        # "HH:MM" 24h string
    "duration",       # e.g. "1h 05m"
    "stops",          # int: 0 = non-stop, 1 = one stop, etc.
    "price",          # int: total price in INR
    "from_city",      # e.g. "Chennai" — injected by normalizer
    "to_city",        # e.g. "Bengaluru" — injected by normalizer
    "date",           # "YYYY-MM-DD" — injected by normalizer
    "travel_class",   # "economy" — injected by normalizer
)
```

### `REQUIRED_RAW_FIELDS`

Minimum fields that must be present in Phase 1 raw output (before normalization):

```python
REQUIRED_RAW_FIELDS = (
    "airline",        # must exist
    "flight_number",  # must exist
    "departure",      # must be HH:MM
    "arrival",        # must be HH:MM
    "duration",       # exists (format not strictly validated in raw)
    "stops",          # must be int
    "price",          # must be int > 0
)
```

### `REQUIRED_OFFER_FIELDS`

Fields every entry in `offers_analysis` (Phase 3 output) must contain:

```python
REQUIRED_OFFER_FIELDS = (
    "flight_number",  # identifies the flight
    "airline",        # e.g. "IndiGo"
    "original_price", # int > 0 — base price before coupons
    "fare_details",   # dict (may be empty if booking page failed)
    "coupons",        # list (may be empty — not all flights show coupons)
)
```

---

## 6. Assertions Reference

### Shared helpers (used across multiple tests)

```python
_is_hhmm(value: str) -> bool
# Returns True if value is a valid "HH:MM" string:
# - exactly 5 chars
# - colon at position 2
# - 0 <= hours <= 23, 0 <= minutes <= 59

_parse_hhmm(t: str) -> int
# Converts "HH:MM" to minutes since midnight.
# "06:00" → 360, "12:00" → 720, "23:59" → 1439

validate_raw_flight_schema(flights, platform="ixigo")
# Asserts: len > 0, all REQUIRED_RAW_FIELDS present, price > 0 int,
# stops is int, departure/arrival are HH:MM, platform == "ixigo"

validate_canonical_schema(flights)
# Asserts: len > 0, all CANONICAL_FLIGHT_FIELDS present, price > 0 int

validate_sorted_by_price(flights)
# Asserts: flights[i].price >= flights[i-1].price for all i > 0

validate_no_duplicate_flight_numbers(flights)
# Asserts: no two flights share (airline, flight_number) pair
```

### Test 1 (`test_phase1_extraction`) assertions

| Assertion | Condition |
|---|---|
| Return type | `isinstance(results, list)` |
| Platform | `f["platform"] == "ixigo"` for all flights |
| Required fields | all of `REQUIRED_RAW_FIELDS` present |
| Price type | `isinstance(f["price"], int)` |
| Price value | `f["price"] > 0` |
| Stops type | `isinstance(f["stops"], int)` |
| Departure format | `_is_hhmm(f["departure"])` |
| Arrival format | `_is_hhmm(f["arrival"])` |

### Test 2 (`test_phase1_with_normalization`) assertions

| Assertion | Condition |
|---|---|
| Raw list returned | `isinstance(raw_results, list)` |
| Normalizer returns results | `len(normalized) > 0` |
| 5-flight cap | `len(normalized) <= 5` |
| Canonical schema | all of `CANONICAL_FLIGHT_FIELDS` on every flight |
| Price validity | `isinstance(f["price"], int) and f["price"] > 0` |
| Sort order | `flights[i].price >= flights[i-1].price` |
| No duplicates | no repeated `(airline, flight_number)` pair |
| Platform | `f["platform"] == "ixigo"` for all |

### Test 3 (`test_phase1_with_filters`) assertions

Sub-test A (non-stop):

| Assertion | Condition |
|---|---|
| Return type | `isinstance(raw_nonstop, list)` |
| Stop count | `f["stops"] == 0` for all normalized flights |

Sub-test B (departure window):

| Assertion | Condition |
|---|---|
| Return type | `isinstance(raw_window, list)` |
| Departure in window | `360 <= _parse_hhmm(f["departure"]) <= 720` |

### Test 4 (`test_phase3_offer_extraction`) assertions

| Assertion | Condition |
|---|---|
| Return type | `isinstance(result, dict)` |
| Keys present | `"flights"` and `"offers_analysis"` in `result` |
| Non-empty offers | `len(offers_analysis) > 0` when `flights` is non-empty |
| REQUIRED_OFFER_FIELDS | all fields present on every offer |
| `original_price` | `isinstance(v, int) and v > 0` |
| `fare_details.base_fare` | `isinstance(v, int) and v > 0` (when `fare_details` is non-empty) |
| `coupons` type | `isinstance(coupons, list)` |
| `best_price_after_coupon` | present and `int >= 0` when `coupons` is non-empty |
| Best coupon math | `best == min(c["price_after_coupon"] for c in coupons)` |

### Test 5 (`test_on_progress_callbacks`) assertions

| Assertion | Condition |
|---|---|
| Return type | `isinstance(result, dict)` |
| phase2_start fired | `len(phase2_events) >= 1` |
| phase2_start data type | `isinstance(phase2_data, list)` |
| phase2_start non-empty | `len(phase2_data) > 0` |
| phase2_start fields | `airline`, `flight_number`, `departure`, `arrival`, `price` on every flight |
| offer_extracted data type | `isinstance(offer_data, dict)` |
| offer_extracted fields | `flight_number`, `airline`, `original_price` on every event |

### Test 6 (`test_full_orchestrator_pipeline`) assertions

| Assertion | Condition |
|---|---|
| agent_start sent | `len(agent_starts) > 0` |
| ixigo in agents | `"ixigo" in [m["agent"] for m in agent_starts]` |
| coupon_analysis_scope sent | `len(scope_msgs) > 0` |
| scope.flight_ids | `isinstance(v, list)` |
| scope.count | `isinstance(v, int) and v > 0` |
| results message count | `len(results_msgs) == 1` |
| winner present | `winner is not None` |
| winner.price_effective | `int(price_eff) > 0` |
| with_coupons | `isinstance(v, list) and len(v) > 0` |
| done message count | `len(done_msgs) == 1` |
| done is last | `messages[-1]["type"] == "done"` |

### Test 7 (`test_session_logging`) assertions

| Assertion | Condition |
|---|---|
| session_id type | `isinstance(session_id, str) and len(session_id) > 0` |
| session dir exists | `session_dir.is_dir()` |
| metadata.json exists | `metadata_file.exists()` |
| metadata.session_id | matches returned `session_id` |
| metadata.search_params | `from_city`, `to_city`, `travel_date`, `travel_class`, `agents` all correct |
| metadata.status | `== "in_progress"` initially |
| nova_act_session.log | exists and non-empty |
| execution.json after log_phase | is non-empty list |
| execution last entry | `phase == "test_phase"`, `agent == "ixigo"`, `status == "success"` |
| finalized metadata.status | `== "completed"` |
| finalized timestamp_end | key present |
| finalized summary | key present and is dict |

---

## 7. Environment Setup

### Prerequisites

| Requirement | Details |
|---|---|
| Python 3.11+ | Type hints and async features used throughout |
| AWS account | IAM user with `AmazonBedrockFullAccess` |
| Nova Act | IAM mode — no separate API key needed |
| S3 bucket | For Nova Act workflow definitions (e.g., `s3://fair-wise`) |

### Minimal setup from scratch

```bash
# 1. Create virtual environment (Python 3.11 required)
cd backend/
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
# Edit .env and fill in:
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#   AWS_DEFAULT_REGION=us-east-1
#   NOVA_ACT_S3_BUCKET=your-bucket-name

# 4. Verify AWS credentials work
python3 -c "import boto3; print(boto3.client('sts').get_caller_identity())"

# 5. Run a quick sanity test
./run_test.sh nova          # fast: no browser, just Bedrock
./run_test.sh ixigo --phase1-only  # browser test, Phase 1 only
```

### `.env` key reference

```env
# Required for all tests
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1

# Required for Nova Act (travel agent tests)
NOVA_ACT_S3_BUCKET=your-bucket-name

# Optional: show browser windows
FAREWISE_HEADED=0     # set to 1 to see Nova Act navigate

# Optional: raise max steps if agents hit ActExceededMaxStepsError
NOVA_ACT_MAX_STEPS=50
```

### Enabling Bedrock model access

Nova models are not enabled by default in new AWS accounts:

1. Open https://console.aws.amazon.com/bedrock/
2. Left sidebar → **Model access** → **Modify model access**
3. Enable: Amazon Nova Lite, Amazon Nova Pro, Amazon Nova Multimodal Embeddings
4. Click **Save changes** (typically instant, no review required)

For full setup instructions including IAM policy, S3 bucket creation, and Chrome extension loading, see [../SETUP.md](../SETUP.md).

---

## 8. Log Files

### Test run logs

Every test run via `test_ixigo_e2e.py` (directly or through `run_test.sh`) creates a timestamped log file:

```
backend/logs/agent_ixigo_e2e_<YYYY-MM-DD>_<HH-MM-SS>.log
```

Example:
```
backend/logs/agent_ixigo_e2e_2026-03-15_14-32-07.log
```

This file captures all `log.info/warning/error` output from every test function. It is created by `add_agent_test_file_handler("ixigo_e2e")` called in the `__main__` block of `test_ixigo_e2e.py`.

For `run_test.sh ixigo`, the log file path is printed at the start:
```
Test logs also written to backend/logs/agent_ixigo_e2e_2026-03-15_14-32-07.log
```

### Session-specific logs (from `test_session_logging`)

The session logging test creates a full session directory structure under:

```
backend/logs/<YYYY-MM-DD>/<session_id>/
├── metadata.json           ← search params, status, timestamps
├── nova_act_session.log    ← all Python logging output captured during session
└── execution.json          ← phase timeline (log_phase entries)
```

This mirrors exactly what production searches create. The admin dashboard at `http://localhost:7891/admin` reads these directories.

### Viewing logs during a run

Since `run_test.sh` uses `exec python ...` to replace the shell process, all output goes directly to your terminal. To tee to a file while watching live:

```bash
./run_test.sh ixigo 2>&1 | tee /tmp/ixigo_run.log
```

To inspect a completed log file:

```bash
# Full log
cat backend/logs/agent_ixigo_e2e_2026-03-15_14-32-07.log

# Only PASS/FAIL lines
grep -E "PASS|FAIL|SKIP|ERROR" backend/logs/agent_ixigo_e2e_*.log | tail -20

# Last run's results summary
grep "Results:" backend/logs/agent_ixigo_e2e_*.log | tail -5
```

---

## 9. Adding New Tests

### Pattern: adding a Cleartrip E2E suite

Follow the same structure as `test_ixigo_e2e.py`. The key conventions:

**1. Create the file**

```
backend/tests/test_cleartrip_e2e.py
```

**2. Import and configure**

```python
from agents.cleartrip import CleartripAgent
from nova.flight_normalizer import FlightNormalizer
from session_logger import SessionLogger
from logger import add_agent_test_file_handler, get_logger

log = get_logger(__name__)

TRAVEL_DATE  = "2026-03-22"
ROUTE_FROM   = "Chennai"
ROUTE_TO     = "Mumbai"
TRAVEL_CLASS = "economy"

# Reuse the same field constants:
CANONICAL_FLIGHT_FIELDS = (...)
REQUIRED_RAW_FIELDS = (...)
REQUIRED_OFFER_FIELDS = (...)
```

**3. Write individual test functions**

Each test function must:
- Have a docstring explaining what user action it mimics
- Call `log.info("=== TEST N: <name> ===")` at the top
- Use `assert_ok(condition, message)` for all assertions
- Call `log.info("<name> PASSED (...)")` on success
- Return the result data for use by downstream tests (optional)

```python
def test_cleartrip_phase1_extraction():
    """
    Mimics: User enters Chennai→Mumbai on Cleartrip, clicks Search.
    """
    log.info("=== TEST 1: test_cleartrip_phase1_extraction ===")
    agent = CleartripAgent()
    results = agent.search(
        from_city=ROUTE_FROM,
        to_city=ROUTE_TO,
        date=TRAVEL_DATE,
        travel_class=TRAVEL_CLASS,
        fetch_offers=False,
    )
    assert_ok(isinstance(results, list), "expected list")
    if len(results) == 0:
        log.warning("No flights — pipeline validated")
        log.info("test_cleartrip_phase1_extraction PASSED (0 flights)")
        return results
    validate_raw_flight_schema(results, platform="cleartrip")
    log.info("test_cleartrip_phase1_extraction PASSED (%d flights)", len(results))
    return results
```

**4. Write the suite runner**

```python
def run_all_cleartrip_tests(phase1_only: bool = False) -> dict:
    log.info("══════════  Cleartrip E2E Test Suite  ══════════")
    results = {"passed": [], "failed": [], "skipped": []}

    def _run(name, fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
            results["passed"].append(name)
        except (AssertionError, Exception) as e:
            log.error("FAIL: %s — %s", name, e)
            results["failed"].append(name)

    _run("test_cleartrip_phase1_extraction", test_cleartrip_phase1_extraction)
    # ... add more tests
    return results
```

**5. Add `__main__` block**

```python
if __name__ == "__main__":
    log_path = add_agent_test_file_handler("cleartrip_e2e")
    log.info("Test logs also written to %s", log_path)
    phase1_only = "--phase1-only" in sys.argv
    summary = run_all_cleartrip_tests(phase1_only=phase1_only)
    sys.exit(0 if not summary["failed"] else 1)
```

**6. Register in `run_all_tests.py`**

```python
CLEARTRIP_E2E_TESTS = [
    ("Cleartrip E2E — Full Suite (P1+P2+P3)", "test_cleartrip_e2e.py"),
]
```

And add the `--cleartrip-e2e` flag handling in `main()`.

**7. Register in `run_test.sh`**

Add a `cleartrip` case to the suite dispatch section:

```bash
cleartrip)
  SUITE="cleartrip"
  # parse --phase1-only etc.
  ;;
```

And handle in the dispatch block:

```bash
cleartrip)
  print_banner "Cleartrip E2E"
  cd "$SCRIPT_DIR"
  exec python tests/test_cleartrip_e2e.py $FLAGS
  ;;
```

### Shared helpers to reuse

All validation helpers in `test_ixigo_e2e.py` (`validate_raw_flight_schema`, `validate_canonical_schema`, `validate_sorted_by_price`, `validate_no_duplicate_flight_numbers`, `_is_hhmm`, `_parse_hhmm`) are self-contained and can be copied directly into any new E2E file, or extracted to a shared `tests/helpers.py` module once there are two or more E2E suites.

---

## 10. Changelog

### 2026-03-15 — Initial test suite: Ixigo E2E

- Added `tests/test_ixigo_e2e.py` — 7 tests covering Phases 1–4 + session logging
  - `test_phase1_extraction` — raw extraction schema validation
  - `test_phase1_with_normalization` — normalization + sort + dedup
  - `test_phase1_with_filters` — non-stop and departure window filter validation
  - `test_phase3_offer_extraction` — fare breakdown + coupon extraction
  - `test_on_progress_callbacks` — WebSocket interim event validation
  - `test_full_orchestrator_pipeline` — full WebSocket pipeline with MockWebSocket
  - `test_session_logging` — SessionLogger directory + file structure validation
- Routes: Chennai → Bengaluru (primary), Mumbai → Delhi (secondary normalization)
- Travel date: 2026-03-22 (one week from authoring date 2026-03-15)
- Added `backend/run_test.sh` — venv-activating launcher with suite/phase/headed mode support
- Updated `tests/run_all_tests.py` — added `--headed` flag, ensured `--ixigo-e2e` and `--phase1-only` work correctly
- Added `backend/docs/TESTING.md` — this file
