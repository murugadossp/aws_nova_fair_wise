# Cleartrip Phase 3 — Chronological timing analysis (from run 2026-03-07 22:14)

## Session IDs (from logs)

| ID / prefix | Role |
|-------------|------|
| `019cc92f-8a59-7dc8-8565-29a94e7faa5c` (aa5c) | Main session — search, filter+extract, harvest both URLs |
| `019cc931-0fa5-72d0-9943-a98cd0409627` (9627) | Parallel worker 1 — flight 1 (IX-2935) itinerary URL |
| `019cc931-ed3d-7792-8211-7cb3fe5f49d1` (49d1) | Parallel worker 2 — flight 2 (6E-886) itinerary URL |

Workflow runs: `019cc92f-88d0-...` (main), `019cc931-0e4b-...` (worker 1), `019cc931-e25a-...` (worker 2).

---

## Chronological timeline

| Time (IST) | Event |
|------------|--------|
| **22:14:15** | Test start; main session (aa5c) starts on search URL. |
| **22:14:35** | Combined filter+extract act starts (departure=Early morning, Morning). |
| **22:15:13** | Phase 1 done — 5 flights; **Harvest [1/2]** starts (Book IX-2935). |
| **22:15:13** | Main session: act "Scroll up or down… Book Air India Express IX-2935 ₹7440". |
| ~22:15:34 | Main session: Book done; **select_fare_continue_only** act (~21.3s). |
| **22:15:57** | **Harvest [1/2] URL captured** (IX-2935). **`on_url_harvested(0, …)` runs → task 1 submitted to executor.** |
| **22:15:57** | **Harvest [2/2] starts** — main session does `goto(search_url)` then Book 6E-886. |
| **22:16:01** | **Parallel worker 1 starts** (workflow 019cc931-0e4b) — session 9627 **opens flight 1 itinerary URL** (NIAHab30ee1f…). |
| 22:16:01–22:16:53 | **Overlap:** main session (aa5c) is doing Book 6E-886 + Continue; parallel 9627 is doing coupons then fare summary on flight 1. |
| **22:16:53** | **Harvest [2/2] URL captured** (6E-886). **`on_url_harvested(1, …)` runs → task 2 submitted.** |
| **22:16:55** | **Parallel worker 2 starts** (workflow 019cc931-e25a) — session 49d1 opens flight 2 itinerary URL (NIAH2f0f4302…). |
| 22:16:55 onward | Worker 1 (9627) hits **ActExceededMaxStepsError** (16 steps) on `extract_fare_summary_booking` (coupon popup). Worker 2 (49d1) completes coupons + fare summary. |
| **22:18:30** | Worker 1 (9627) session ends FAILED; main and worker 2 already finished. |

---

## What’s wrong (findings)

### 1. We don’t wait for both harvest URLs before starting parallel work

- **When:** As soon as the first itinerary URL is captured (22:15:57), we call `on_url_harvested(0, …)` and **submit task 1**.
- **Effect:** Parallel worker 1 starts at 22:16:01 while the main session is still harvesting the second URL (Book 6E-886, then Continue). So we have **overlap**: main session harvesting flight 2 and worker 1 analyzing flight 1 at the same time.
- **User expectation:** “We did not wait for 2 harvest url” — i.e. wait until **both** URLs are harvested, then start all parallel analysis.

### 2. First flight’s itinerary URL is opened twice (“duplicate harvest URL session”)

- **First open:** Main session (aa5c) clicks Book → Continue and **lands on** flight 1’s itinerary page; we read `nova.page.url` and then call `nova.page.goto(search_url)` for harvest 2. So the main session **opens** that URL once.
- **Second open:** Parallel worker 1 (9627) starts with `starting_page=itinerary_url` for the **same** flight 1 URL.
- **Effect:** The same itinerary URL is loaded in two different sessions (main then worker 1). That’s the “duplicate harvest url session” / “we did twice analyze” for the first flight’s URL.

### 3. Order of operations

- Current: Harvest URL 1 → submit task 1 → harvest URL 2 → submit task 2 → wait for all futures.
- Desired (to match “wait for 2 harvest url” and avoid confusion): Harvest URL 1 → harvest URL 2 → **then** submit task 1 and task 2 → wait for all futures. That way no parallel worker starts until both URLs are in hand.

---

## Recommended fix

1. **Harvest-only first, then submit all tasks**  
   In `search()`, call `_harvest_itinerary_urls(..., on_url_harvested=None)` so that **no** parallel tasks are submitted during harvest. Collect the full `harvested` list (both URLs).  
   After `_harvest_itinerary_urls` returns, loop over `harvested` and submit one `_extract_offers_from_itinerary_url` task per item (with `do_payment_fare=(idx == 0)`), then wait for all futures.  
   That way we **wait for 2 harvest URLs** before any parallel analysis starts, and the timeline is clear: harvest 1 → harvest 2 → start both workers.

2. **Duplicate open of first URL**  
   The first flight’s URL will still be “opened” twice (main session to capture URL, then worker 1 to extract). To avoid that we’d have to either:  
   - Do extraction for flight 1 in the main session (e.g. re-introduce “extract first in session” and only submit tasks for `idx >= 1`), or  
   - Accept that the main session only harvests and each URL is opened again in its parallel worker.  
   The code change above does not remove this duplicate open; it only fixes “don’t start parallel work until both URLs are harvested.”

---

## Approximate durations (from log)

| Step | Approx duration |
|------|------------------|
| Filter+extract (Phase 1) | ~37.6s |
| Harvest 1 (Book + Continue) | ~44s (22:15:13 → 22:15:57) |
| Harvest 2 (goto + Book + Continue) | ~56s (22:15:57 → 22:16:53) |
| Select fare continue (flight 1) | ~21.3s |
| Select fare continue (flight 2) | ~31.6s (from log snippet) |
| Parallel worker 1 (9627) | ~1m 46s (failed at max steps) |
| Parallel worker 2 (49d1) | ~1m 10s (2 acts) |
