# Ixigo Agent — Search URL, Filters, and Bot-Detection

This document describes how the Ixigo agent builds the flight search URL, applies
filters, and defeats bot detection. The orchestrator passes the same input shape to
all travel agents.

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

## 2. Flow — SPA boot + direct URL navigation

The agent uses a two-step navigation strategy to avoid bot detection:

1. **Boot the SPA at the homepage** (`https://www.ixigo.com/`) — this loads the React
   JS bundle and initializes session cookies.
2. **Apply bot-detection countermeasures** — UA masking, JS fingerprint overrides,
   sensor warm-up, mouse movement (see section 6).
3. **Navigate to the pre-filtered search URL** via `page.goto()` — the JavaScript
   router handles the route since the SPA is already running.
4. **Wait step** — a dedicated Nova Act instruction waits for flight listings to render.
5. **Extract** — a separate Nova Act instruction extracts up to 5 flights.

---

## 3. URL parameters

Base path: `https://www.ixigo.com/search/result/flight`

| Param     | Values / format | When added |
|-----------|------------------|------------|
| `from`    | IATA code (e.g. BOM, BLR) | Always |
| `to`      | IATA code | Always |
| `date`    | DDMMYYYY (e.g. `18032026` for 18 Mar 2026) | Always |
| `adults`  | 1 | Always |
| `children`| 0 | Always |
| `infants` | 0 | Always |
| `class`   | `e` \| `b` \| `p` \| `f` (economy, business, premium economy, first) | Always |
| `intl`    | `n` | Always |
| `sort_type` | `cheapest` \| `quickest` \| `earliest` \| `best` | Always (default `cheapest`) |
| `stops`   | Integer (e.g. `0` for non-stop) | When `max_stops` filter is set |
| `takeOff` | Comma-separated bucket values (e.g. `EARLY_MORNING,MORNING`) | When `departure_window` filter is set |
| `landing` | Comma-separated bucket values | When `arrival_window` filter is set |

**sort_type mapping** from planner `sort_by`: `price` → `cheapest`, `duration` → `quickest`, `departure` → `earliest`; default `cheapest`.

**Wait strategy:** The agent uses a dynamic wait keyed to the flight list container so it can proceed as soon as results are in the DOM (no fixed 5s delay). Config uses the stable Ixigo selector `[data-testid='flight-list']` and `wait_for_selector_timeout_ms` (e.g. 15000). If the selector fails or times out, the agent falls back to a short static sleep so the run still completes. This avoids scraping skeleton loaders and reduces dead time on fast connections.

**Reference selectors (Ixigo DOM):** Main list `[data-testid='flight-list']`, individual card `.flight-card` or `[data-testid='flight-card']`, container `.search-results-container`.

---

## 4. Time bucket mapping

`departure_window` and `arrival_window` are `["HH:MM", "HH:MM"]` ranges. The agent
maps overlapping time buckets to Ixigo's URL values using `config.yaml` `time_buckets`.

| Bucket (label)   | Time range (minutes) | Ixigo param value |
|------------------|----------------------|-------------------|
| Early morning    | 0 - 480 (00:00-08:00)   | `EARLY_MORNING` |
| Morning          | 480 - 720 (08:00-12:00)  | `MORNING` |
| Afternoon        | 720 - 960 (12:00-16:00)  | `AFTERNOON` |
| Evening          | 960 - 1200 (16:00-20:00) | `EVENING` |
| Night            | 1200 - 1440 (20:00-24:00)| `NIGHT` |

**Overlap logic:** A window `[lo, hi]` selects every bucket whose interval overlaps
`[lo, hi]`. If all buckets would be selected, no `takeOff`/`landing` param is added
(no filter). Multiple selected buckets are joined with a comma.

**Example:** `departure_window=["06:00", "12:00"]` overlaps Early morning (06:00-08:00)
and Morning (08:00-12:00), producing `takeOff=EARLY_MORNING,MORNING`.

---

## 5. Config and code

- **config.yaml**
  - `base_url`: `https://www.ixigo.com`
  - `time_buckets`: list of bucket definitions with `label`, `start`, `end`, `ixigo_value`
  - `city_codes`: 26 cities mapped to IATA codes
  - `class_codes`: economy, business, premium_economy, first
  - `steps.wait`: dedicated wait instruction (do NOT click REFRESH)
  - `steps.extraction`: `instruction_file: instructions/wait_and_extract.md` and schema
- **instructions/wait_and_extract.md**
  - Dismiss popups, scroll to trigger lazy-loading, extract up to 5 cheapest flights.
  - Explicit guard: "Do NOT click REFRESH or SEARCH."
- **agent.py**
  - `_build_search_url()`: builds URL with filter params (`stops`, `takeOff`, `landing`)
  - `_resolve_time_buckets()`: maps `[HH:MM, HH:MM]` windows to Ixigo bucket values
  - `search()`: SPA boot sequence + all bot-detection layers + extraction

---

## 6. Bot detection countermeasures

The agent applies five layers of anti-detection (same as MakeMyTrip agent):

| Layer | Technique | Implementation |
|-------|-----------|----------------|
| 1 | SPA boot sequence | Start at homepage, `goto(search_url)` after JS loads |
| 2 | HTTP header masking | `set_extra_http_headers()` — real Chrome/122 UA + sec-ch-ua |
| 3 | JS fingerprint overrides | `add_init_script()` — 10+ navigator/window properties |
| 4 | Sensor warm-up | `networkidle` + `sleep(3)` dwell on homepage |
| 5 | Behavioral signals | `mouse.move()` with natural pauses before navigation |

Additional guards:
- **Page drift guard**: checks URL after wait step, restores if drifted
- **No REFRESH rule**: extraction instruction explicitly forbids clicking REFRESH

See [`CHANGELOG_2026-03-11.md`](CHANGELOG_2026-03-11.md) for the full details of each layer.

---

## 7. References

- Ixigo agent: [`backend/agents/ixigo/agent.py`](../../agent.py)
- Ixigo config: [`backend/agents/ixigo/config.yaml`](../../config.yaml)
- Bot detection guide: [`backend/docs/BOT_DETECTION_GUIDE.md`](../../../docs/BOT_DETECTION_GUIDE.md)
- Orchestrator: `backend/agents/orchestrator.py`
