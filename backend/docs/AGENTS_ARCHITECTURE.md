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
├── cleartrip/
│   ├── __init__.py          # from .agent import CleartripAgent; __all__ = ["CleartripAgent"]
│   ├── agent.py             # CleartripAgent class; loads config, runs Nova Act
│   └── config.yaml          # workflow_name, base_url, steps (instructions + schemas)
├── goibibo/
│   ├── __init__.py
│   ├── agent.py
│   └── config.yaml
├── makemytrip/
│   ├── __init__.py
│   ├── agent.py
│   └── config.yaml
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

Imports elsewhere (orchestrator, main, tests) use the package: `from agents.cleartrip import CleartripAgent`, `from agents.goibibo import GoibiboAgent`, etc. The test runner `tests/run_agent.sh` invokes test scripts by name (e.g. `test_cleartrip_agent.py`); it does not depend on the agents folder structure.

---

## config.yaml structure

Each agent’s `config.yaml` is loaded at module import time from the directory containing `agent.py` (e.g. `Path(__file__).resolve().parent / "config.yaml"`). No shared config loader is used; each agent is self-contained.

### Common keys

| Key | Description |
|-----|-------------|
| `workflow_name` | Nova Act workflow name (e.g. `farewise-cleartrip`). Can be overridden by env var (e.g. `NOVA_ACT_WORKFLOW_CLEARTRIP`). |
| `base_url` | Site base URL; used for building search URLs and for the `{{base_url}}` placeholder in instructions. |

### Travel agents (Cleartrip, Goibibo, MakeMyTrip)

Additional keys:

| Key | Description |
|-----|-------------|
| `city_codes` | Map of city name (lowercase) to IATA/code (e.g. `mumbai: BOM`). Used for URL construction. |
| `default_criteria` | Default search criteria when the user does not pass `user_prompt` (e.g. `"top 5 cheapest flights"`). |
| `max_steps_default` | Default `max_steps` for `nova.act()`; can be overridden by `NOVA_ACT_MAX_STEPS`. |

**Steps:**

- **`wait`** — Single instruction (e.g. “Wait for the flight results to fully load.”) run once before extraction.
- **`extraction`** — `instruction` (multi-line, with placeholders `{{criteria}}`, `{{base_url}}`) and `schema` (JSON Schema for the flight array). The agent substitutes placeholders at runtime.
- **`offers`** (Cleartrip only) — Optional second act: `instruction` and `schema` for offers + suggestion. Run only after extraction succeeds and when `fetch_offers=True`.

### Product agents (Amazon, Flipkart)

- **`steps.extraction`** — `instruction` (placeholders `{{max_results}}`, `{{base_url}}`) and `schema` for the product array.
- **`steps.pre`** (optional, e.g. Flipkart) — One instruction run before extraction (e.g. close login popup). No schema.

### Placeholders

Instructions in `config.yaml` can use placeholders filled in by the agent at runtime:

- `{{criteria}}` — User or default search criteria (travel agents).
- `{{base_url}}` — From config `base_url`.
- `{{max_results}}` — Number of results to extract (product agents).

The agent uses a simple replace (e.g. `instruction.replace("{{criteria}}", criteria)`) so the exact placeholder names must match the keys passed from code.

### Schema format

Schemas in YAML match JSON Schema. For nullable types use a list with the string `"null"` (e.g. `type: [integer, "null"]`) so that the value is the string `"null"` for JSON Schema and not YAML’s `null`. Example:

```yaml
original_price: { type: [integer, "null"] }
```

---

## Agent class pattern

1. **Load config once** at module level: `_CONFIG = yaml.safe_load(open(Path(__file__).parent / "config.yaml"))`.
2. **Resolve backend root** for imports: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))` so that `logger`, `nova_auth`, and `agents.act_handler` can be imported.
3. **In `search()`:**  
   - Build URL and workflow name (from config + env overrides).  
   - Run `Workflow` + `NovaAct` context managers.  
   - For each step (wait, extraction, optional offers): get `instruction` and `schema` from `_CONFIG["steps"][...]`, substitute placeholders, call `nova.act(instruction, schema=..., max_steps=...)`.  
   - Parse result: if `nova.act()` returns `ActGetResult`, use `parsed_response`; otherwise treat as list/dict.  
   - Normalize results (e.g. prepend `base_url` to relative URLs).  
   - On exception: travel agents call `ActExceptionHandler.handle(e, "AgentName", context)` and return its return value (e.g. `[]`). Product agents may log and return `[]` or use the same handler if desired.

Cleartrip can return either a **list** of flight dicts (when no offers step or offers step skipped/failed) or a **dict** `{"flights": [...], "offers_analysis": [...], "suggestion": "..."}` when the offers step succeeds. The orchestrator handles both shapes.

---

## Shared components

- **`agents/act_handler.py`** — `ActExceptionHandler.handle(exc, agent_name, context)`. Used by Cleartrip, Goibibo, MakeMyTrip to log and return a consistent value (e.g. empty list) on Nova Act or other errors. See [EXCEPTION_HANDLING.md](EXCEPTION_HANDLING.md).
- **`agents/orchestrator.py`** — `TravelOrchestrator` and `ProductOrchestrator` import each agent from its package and call `agent.search(...)`. For Cleartrip, if the result is a dict with `"flights"`, they take `result["flights"]` for the combined list and pass `offers_analysis` / `suggestion` to the client when present.

---

## Adding a new agent

1. Create a folder under `agents/`, e.g. `agents/newsite/`.
2. Add **`config.yaml`** with `workflow_name`, `base_url`, and `steps` (at least `extraction` with `instruction` and `schema`). Use placeholders as needed.
3. Add **`agent.py`** with a class that loads the config, builds the search URL, runs `Workflow`/`NovaAct`/`nova.act()` using config instructions and schemas, and normalizes results. On exception, call `ActExceptionHandler.handle(...)` if the agent should behave like the travel agents.
4. Add **`__init__.py`** with `from .agent import NewSiteAgent` and `__all__ = ["NewSiteAgent"]`.
5. Optionally add the new agent to `agents/__init__.py` and to the orchestrator and/or `tests/run_agent.sh` if it should be used in a flow or runnable via the script.

No changes to a central “config loader” are required; each agent reads its own `config.yaml` from its package directory.
