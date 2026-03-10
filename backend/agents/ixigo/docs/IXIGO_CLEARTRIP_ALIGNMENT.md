# Ixigo Agent — Search URL and Filters

This document describes how the Ixigo agent builds the flight search URL and applies filters. The orchestrator passes the same input shape to all travel agents; Ixigo encodes **all filters in the search URL** (no UI pre_filter step).

---

## 1. Input (orchestrator contract)

`TravelOrchestrator.run_travel` calls the agent with:

| Parameter      | Type   | Description |
|----------------|--------|-------------|
| `from_city`    | str    | Origin city name (e.g. "mumbai", "delhi") |
| `to_city`      | str    | Destination city name |
| `date`         | str    | Departure date in `YYYY-MM-DD` |
| `travel_class` | str    | e.g. "economy", "business" |
| `filters`      | dict   | Planner-derived filters (see below) |

**filters:**

- `departure_window`: `["HH:MM", "HH:MM"]` or `None` — requested departure time range
- `arrival_window`: `["HH:MM", "HH:MM"]` or `None` — requested arrival time range
- `max_stops`: `int` or `None` — e.g. `0` for non-stop only
- `sort_by`: `str` — e.g. `"price"` (used in extraction criteria text; normalizer also applies)

---

## 2. Ixigo-specific behaviour: form-fill flow (like a real user)

The agent **does not** open a direct results URL. It mimics a user step by step:

1. **Open the base URL** (`search_form_url` from config, e.g. `https://www.ixigo.com`).
2. **Fill the search form:** Select source city, destination city, one-way, and date (instruction: `instructions/fill_search_form.md`), then click Search.
3. **After the results page loads:** One combined act to wait for load and extract flights (`instructions/wait_and_extract.md`).

**Flow:** Open base URL → act: fill form (source, destination, one-way, date) + search → act: wait + extract flights. All instructions are in `.md` files referenced from `config.yaml`.

---

## 3. URL parameters

Base path: `https://www.ixigo.com/search/result/flight`

| Param     | Values / format | When added |
|-----------|------------------|------------|
| `from`    | IATA code (e.g. HYD, BLR) | Always |
| `to`      | IATA code | Always |
| `date`    | DDMMYYYY (e.g. `10062026` for 10 Jun 2026) | Always |
| `adults`  | 1 | Always |
| `children`| 0 | Always |
| `infants` | 0 | Always |
| `class`   | `e` \| `b` \| `f` \| `pe` (economy, business, first, premium economy) | Always |
| `source`  | `Search+Form` | Always |

**Note:** `stops`, `takeOff`, and `landing` are **not** added to the URL so loading mimics a user who only selected source, destination and date. Filtering (e.g. by departure time or stops) can be applied later by the normalizer or by adding params back if needed.

---

## 4. Time bucket mapping

`departure_window` and `arrival_window` are `["HH:MM", "HH:MM"]` ranges. The agent maps the overlapping time buckets to Ixigo’s URL values using `config.yaml` `time_buckets` (each entry has `label`, `start`, `end`, `ixigo_value`).

| Bucket (label)   | Time range  | Ixigo param value |
|------------------|-------------|--------------------|
| Early morning    | 00:00–08:00 | `EARLY_MORNING`    |
| Morning          | 08:00–12:00 | `MORNING`          |
| Afternoon        | 12:00–16:00 | `AFTERNOON`        |
| Evening          | 16:00–20:00 | `EVENING`          |
| Night            | 20:00–24:00 | `NIGHT`            |

Overlap logic: a window `[lo, hi]` selects every bucket whose interval overlaps `[lo, hi]`. If all buckets would be selected, no `takeOff`/`landing` param is added (no filter). Multiple selected buckets are joined with a comma and URL-encoded (e.g. `takeOff=EARLY_MORNING%2CMORNING`).

---

## 5. Config and code

- **config.yaml**
  - `base_url`, `search_form_url`: page to open first (default `https://www.ixigo.com`).
  - `steps.fill_and_search`: `instruction_file: instructions/fill_search_form.md`, `max_steps: 30`.
  - `steps.extraction`: `instruction_file: instructions/wait_and_extract.md` and `schema`.
- **instructions/fill_search_form.md**
  - Select source `{{from_city}}` ({{from_code}}), destination `{{to_city}}` ({{to_code}}), one-way, date `{{date}}`, then click Search.
- **instructions/wait_and_extract.md**
  - After results load: wait (dismiss login/banner), then extract flights matching `{{criteria}}`. Placeholders: `{{criteria}}`, `{{base_url}}`.
- **agent.py**
  - `_get_instruction(step_cfg)`: reads instruction from `instruction_file`.
  - `search()`: opens Nova Act at `search_form_url` → act: fill form + search → act: wait + extract.

---

## 6. References

- Ixigo agent: [backend/agents/ixigo/agent.py](../../agent.py)
- Ixigo config: [backend/agents/ixigo/config.yaml](../../config.yaml)
- Orchestrator: `backend/agents/orchestrator.py` — `run_travel` builds route and filters from planner output.
