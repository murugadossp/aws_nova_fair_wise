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
│   └── config.yaml
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
| `class_codes` | Map of travel class to URL code (e.g. `economy: e`). Ixigo only — used in the `?class=` URL parameter. |

> **Note:** `default_criteria` has been removed. Search criteria are now built at runtime from the structured `filters` dict via the `_filters_to_criteria(filters)` static method on each agent class. If `filters` is `None`, the method returns `"top 5 cheapest flights sorted by price ascending"`.

**Steps:**

- **`wait`** — Single instruction run once before extraction. Can be inline (`instruction`) or from a file (`instruction_file`, e.g. `instructions/wait.md`).
- **`extraction`** — Instruction and `schema` (JSON Schema for the flight array). Cleartrip uses a **two-layer prompt**: `site_adapter_file` (stable Cleartrip UI knowledge) + `extractor_file` (task with `{{criteria}}`, `{{base_url}}`). The agent loads both and concatenates them at runtime so the extraction prompt stays small and site knowledge is reusable.
- **Offers** (Cleartrip only) — When `fetch_offers=True`, after extraction the agent harvests itinerary URLs (combined `book_then_continue` act) and can run parallel or sequential offer extraction (e.g. `select_fare_extract_coupons`, skip add-ons, fill traveler, extract fare breakdown). Returns `{ "flights", "offers_analysis" }` when offers are requested.

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

1. Create a package under `agents/`, e.g. `agents/newsite/`.
2. Add **`config.yaml`** with `workflow_name`, `base_url`, `city_codes`, `max_steps_default`, and `steps` (at least `wait` + `extraction` with `instruction` and `schema`). Use `{{criteria}}` and `{{base_url}}` placeholders. Add `class_codes` if the site's URL uses a class code parameter (like Ixigo).
3. Add **`agent.py`** with:
   - `_filters_to_criteria(filters: dict | None) -> str` static method (copy pattern from Ixigo/MakeMyTrip)
   - `search(from_city, to_city, date, travel_class=”economy”, filters=None)` signature
   - Pop `NOVA_ACT_API_KEY`, call `get_or_create_workflow_definition(workflow_name)`, run `Workflow`/`NovaAct`
   - On exception: `return ActExceptionHandler.handle(e, “NewSite”, context)`
4. Add **`__init__.py`** with `from .agent import NewSiteAgent` and `__all__ = [“NewSiteAgent”]`.
5. Add the agent key to `_TRAVEL_AGENTS` in `agents/orchestrator.py`.
6. Add a test file `tests/test_newsite_agent.py` (copy pattern from `test_cleartrip_agent.py` or `test_ixigo_agent.py`) and call `validate_flight_schema` (or an equivalent validator) on the returned flights so schema and URL checks are enforced.

No changes to a central “config loader” are required; each agent reads its own `config.yaml` from its package directory.
