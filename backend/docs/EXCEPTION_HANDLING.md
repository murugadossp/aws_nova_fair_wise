# Exception Handling — Nova Act Agents

This document describes how Nova Act agent errors are handled so that search flows fail gracefully and future changes stay consistent.

---

## Design

- **Search logic lives in each agent class** (Cleartrip, Goibibo, MakeMyTrip). The agent’s `search()` method contains the full Workflow/NovaAct/act logic.
- **Each agent catches exceptions locally** with a single generic `except Exception as e` around that logic.
- **The agent does not handle the exception itself.** It passes the exception to a **central handler class**, which inspects the type and decides what to log and what to return.
- **The handler never runs agent code.** It only receives an exception and context; it logs and returns a value (e.g. empty list).

```
Agent.search()
  try:
    # Workflow / NovaAct / act / build results
    return results
  except Exception as e:
    return ActExceptionHandler.handle(e, "AgentName", context)
```

---

## Central handler: `ActExceptionHandler`

**Location:** `agents/act_handler.py`

**Class:** `ActExceptionHandler`  
**Method:** `handle(exc: Exception, agent_name: str, context: dict[str, Any]) -> list[dict]`

### Responsibilities

1. **Inspect exception type** (e.g. `isinstance(exc, ActAgentError)`).
2. **Log appropriately** (warning for known agent errors, error for others).
3. **Return the value the agent should return** (e.g. empty list `[]`).

### Exception types and behavior

| Exception type | Log level | Action |
|----------------|-----------|--------|
| `ActAgentError` (and subclasses: `ActExceededMaxStepsError`, `ActInvalidModelGenerationError`, `ActAgentFailed`, etc.) | Warning | Log with agent name, context, exception type, and optional step count from `exc.metadata`; return `[]`. |
| Any other `Exception` | Error | Log with agent name, context, and exception; return `[]`. |

### Context

`context` is a dict used only for log messages, e.g.:

- Travel agents: `{"from": from_city, "to": to_city, "date": date}`
- Product agents (if you add this pattern): `{"query": query}`

---

## Adding a new agent

1. Implement `search()` (or equivalent) with your Workflow/NovaAct/act logic inside a **try** block; return the results list at the end of the try.
2. Add a single **except** block: `except Exception as e: return ActExceptionHandler.handle(e, "<AgentDisplayName>", context)`.
3. Build a **context** dict that helps with debugging (e.g. route, query, date) and pass it to `handle()`.

Do **not** duplicate exception type checks or logging in the agent; keep that in `ActExceptionHandler.handle()`.

---

## Extending the handler

To support new behavior (e.g. return partial results for a specific exception type, or different log levels):

1. In `agents/act_handler.py`, add a new branch in `ActExceptionHandler.handle()` (e.g. `elif isinstance(exc, SomeNewError): ...`).
2. Update this document with the new exception type and behavior.

---

## Nova Act SDK exception reference

Relevant exception types from `nova_act` (all under `ActAgentError` when applicable):

- **ActExceededMaxStepsError** — Max steps reached without a return.
- **ActInvalidModelGenerationError** — Model output invalid (e.g. token limit, parse error, or **schema validation failed**).
- **ActAgentFailed** — Agent reported it could not complete the task.

Handling is unified under `ActAgentError`; subclasses are not required to be listed explicitly unless you want different behavior per type.

---

## Schema validation (matches_schema = False)

When the SDK returns `valid_json = True` but `matches_schema = False`, the model’s JSON is valid but does not satisfy the schema sent to `nova.act(..., schema=...)`.

**Common cause: placeholders in the schema.** If the schema in `config.yaml` contains placeholders like `{{base_url}}` (e.g. in a `pattern` for `url`), they must be **substituted at runtime** before passing the schema to the SDK. Otherwise the validator checks the response against the literal string `"{{base_url}}"` and real values (e.g. `https://www.cleartrip.com/`) fail. The Cleartrip agent does this via `_schema_substitute_base_url()` so that the URL pattern becomes the actual base URL (regex-escaped) before validation.
