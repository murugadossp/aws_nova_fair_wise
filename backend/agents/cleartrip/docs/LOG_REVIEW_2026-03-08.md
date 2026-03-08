# Cleartrip agent log review — 2026-03-08 (08:46 run)

## Chronological time breakdown

| # | Phase / step | Start (log time) | Duration | Cumulative |
|---|----------------|------------------|----------|------------|
| 0 | Test init, workflow definition | 08:46:26 | ~1.5s | — |
| 1 | **Phase 1** — combined filter + extract | 08:46:40 | **40.1s** | 40.1s |
| 2 | Harvest [1/2] — Book (IX-2935) | 08:47:21 | **14.3s** | 54.4s |
| 3 | Harvest [1/2] — Continue → Review itinerary | 08:47:36 | **21.1s** | 75.5s |
| 4 | Harvest [2/2] — Book (6E-537) | 08:47:58 | **12.8s** | 88.3s |
| 5 | Harvest [2/2] — Continue → Review itinerary | 08:48:11 | **14.4s** | 102.7s |
| — | Session end, Phase 2/3 (normalizer + validate) | 08:48:30 | &lt;1s | **~1m 43s** |

**Total Nova Act session:** 1m 42.8s across 5 act calls.

---

## Anomalies

### 1. Parallel offer extraction is disabled (harvest-only)

When `use_parallel_offers: true`, the agent only harvests itinerary URLs and builds a minimal `offers_analysis` (empty `coupons`, empty `fare_breakdown`). The code that would launch parallel Nova Act sessions to open each harvested URL and extract coupons + fare is commented out (`# ── HARVEST-ONLY TEST ──` / `# TODO: re-enable` in `agent.py`).

- **Effect:** Phase 3 validation passes (it only requires `additional_urls.itinerary` and basic fields) but logs “fare_breakdown is empty” and “coupons=0”.
- **Fix:** Re-enable the parallel extraction block after harvest so that each harvested URL is opened in a separate session and coupons + fare breakdown are filled.

### 2. No other logic errors

- Filtering and sorting are correct (7 raw → 4 filtered, departure window 07:00–10:00).
- Harvest captures 2/2 URLs; both match `/flights/itinerary/.../info`.

---

## Nova Act “wasted” thinking / inefficiency

### Phase 1 (40.1s)

- **Scroll sidebar** → **Click Early morning** → **Click Morning** → **Scroll main** → **Extract 7 flights, return.**
- Each of the two filter clicks uses one think + one click; that’s expected. One combined instruction (“click Early morning and Morning”) could reduce one round but might be brittle.
- The main scroll is to see all cards; the final think aggregates 7 flights. No obvious waste; the step count is reasonable for the task.

### Harvest — Book (14.3s, 12.8s)

- **Think 1:** “Find card, click Book” → `agentClick`.
- **Think 2:** “Popup visible, task complete, empty return.”
- The second step is only confirmation + return. **Optimization:** Instruction could say “Click Book; as soon as any dialog/popup appears, return immediately” to encourage a single observation and return. May save one round if the model complies.

### Harvest — Continue (21.1s, 14.4s)

- **Think 1:** “Click Continue” → `agentClick`.
- **Think 2:** “Page changed to Review your itinerary, task complete, empty return.”
- Most of the time is post-click: navigation (~5–15s) plus one observation + think. The agent cannot return in the same step as the click; it must see the new page.
- **Optimization (obsolete):** Harvest now uses the combined `book_then_continue` act only; `select_fare_continue_only` was removed.

---

## Harvest URL efficiency

- **Flow:** For each of the top 2 flights: Book → Continue → `wait_for_url` (glob) → capture `page.url` → `goto(search_url)` for next. Sequential in one session; no duplicate URL opens.
- **Efficiency:** Good. No redundant work; URLs are correct; `wait_for_url("**/flights/itinerary/**/info", timeout=8000)` ensures we capture the itinerary page.
- **Time per flight:** ~31s (14.3 + 21.1 and 12.8 + 14.4). The Continue step dominates (~56% of harvest time). The only lever left without changing the Nova Act contract is reducing max_steps for the Continue act.

---

## Optimization summary

| Item | Recommendation |
|------|----------------|
| **Re-enable parallel extraction** | After harvest, run parallel sessions (or sequential fallback) to fill coupons and fare_breakdown so Phase 3 validates full data. |
| **Harvest** | Use combined `book_then_continue` act only (no separate continue step). |
| **Book act** | Optional: tighten instruction to “return as soon as any popup/dialog appears” to try to save one think round. |
| **Phase 1** | Keep as-is; optional later: single instruction for “select Early morning + Morning” if we want to try one fewer round. |
