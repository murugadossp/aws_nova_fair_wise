# Cleartrip Agent — Flow, Timings & Optimizations

This document describes the Cleartrip Nova Act agent pipeline: phases, per-component timings, and the parallel Phase 3 flow (harvest itinerary URLs then extract coupons and fare in parallel Nova sessions).

---

## 1. Pipeline overview

| Phase | What happens | Where |
|-------|----------------|------|
| **Phase 1** | Single act: apply time filters (e.g. Early morning, Morning) + extract all flight cards from results page | Nova Act (browser) |
| **Phase 2** | Filter by `departure_window` and `max_stops`, sort, deduplicate | Python (`FlightNormalizer`) |
| **Phase 3** | **Main session:** harvest only — Book → Continue for top N flights, capture itinerary URL for each (no extraction). **Then** 2 parallel Nova Act sessions: one opens URL1 with **full flow** (coupons + payment page → fare breakdown); one opens URL2 with **coupons-only** flow. Convenience_fee from the full-flow session is reused for the other offer. | Nova Act (main harvest + 2 parallel sessions) |

Phase 3 runs only when `fetch_offers=True`. Top N is `offers_top_n` in config (default 2). When `use_parallel_offers` is true (default), Phase 3 uses harvest + parallel extraction; otherwise a single session does everything sequentially.

---

## 2. Phase 3 flow

**Parallel path (default, `use_parallel_offers: true`):**

1. **Harvest only (main session):** For each of top N flights: navigate back if needed, Book → Select fare (VALUE) + Continue → capture itinerary URL. No extraction in main; no opening the same URL again in main.
2. **Parallel extraction:** N Nova Act sessions (e.g. 2), each starting at one harvested URL:
   - **Session for flight 1 (idx 0):** `do_payment_fare=True` — extract coupons + booking fare summary, then skip add-ons → fill traveler → payment page → full fare breakdown (provides convenience_fee and payment URL).
   - **Session for flight 2 (idx 1):** `do_payment_fare=False` — extract coupons + booking fare summary only (coupons-only flow).
3. **Merge:** Reuse the first offer’s `convenience_fee` for other offers’ `fare_breakdown` via `_apply_convenience_fee_from_first`.

**Sequential path** (`use_parallel_offers: false`): One session does, per flight, Book → Select fare + coupons → (first flight only: fill_traveler_proceed → extract_fare_breakdown; others: extract_fare_summary_booking only). Same convenience_fee reuse applied after.

Result per flight: `flight_number`, `airline`, `original_price`, `fare_type`, `coupons[]`, `fare_breakdown`, `best_price_after_coupon`, `additional_urls.itinerary`, `additional_urls.payment`.

---

## 3. Time breakdown (from a real run)

**Run:** 2026-03-07, Bengaluru→Hyderabad, 2 offers. Wall clock **17:57:30 → 18:03:51** (~6m 21s). **Nova Act “Time Worked”** below is the agent’s reported time per act.

| # | Component | Start (wall) | Approx. time worked | Cumulative (approx.) |
|---|------------|--------------|----------------------|------------------------|
| 1 | Phase 1 (filter + extract) | 17:58:02 | **39.7s** | 39.7s |
| 2 | Book flight (1) | 17:58:42 | 18.8s | 58.5s |
| 3 | Select fare + coupons (1) | 17:59:02 | 40.9s | 1m 39.4s |
| 4 | Fill traveler + skip add-ons (1) | 17:59:44 | **2m 2.8s** | 3m 42.2s |
| 5 | Extract fare breakdown (1) | 18:01:47 | 5.4s | 3m 47.6s |
| 6 | Book flight (2) | 18:01:54 | 11.8s | 3m 59.4s |
| 7 | Select fare + coupons (2) | 18:02:07 | 39.9s | 4m 39.3s |
| 8 | Extract fare summary (booking, 2) | 18:02:51 | **58.8s** then **max_steps hit** | — |

**Session total (Nova Act):** **4m 39.3s across 7 act calls** (act 8 did not complete; see below).

Phase 2 (FlightNormalizer) runs after Phase 1 and takes &lt;1s.

---

### When max_steps is hit: does it return a value?

**No.** When an act hits `max_steps` before the agent calls `return(...)`, Nova Act raises **`ActExceededMaxStepsError`** and does **not** return a parsed value. So:

- There is **no partial or “till that time”** response: the act is aborted, and `nova.act()` throws.
- Our code catches the exception in a `try/except` and leaves `fare_breakdown = {}` for that flight.
- Everything we **did** get before that act (e.g. coupons, `best_price_after_coupon`, itinerary URL) is kept; only the fare summary for that act is missing.

In the run above, **act 8** (extract_fare_summary_booking for flight 2) used **8 steps** (max_steps was 8) trying to close the coupon popup and never reached `return(...)`, so we got empty `fare_breakdown` for the second flight. We increased `max_steps` to 12 and updated the instruction to “dismiss popup first” so the agent can close the dialog and then extract in the same act.

### Regression analysis (parallel path)

When a parallel session (e.g. second flight with coupons-only) runs **extract_fare_summary_booking**, it can hit max_steps and raise `ActExceededMaxStepsError`, leaving fare_breakdown empty. Playwright `CancelledError` and `TargetClosedError` after the run are teardown noise when parallel Chrome sessions close. **Mitigations:** (1) `_apply_convenience_fee_from_first` fills a minimal fare_breakdown for offers with empty fare_breakdown (convenience_fee from first, total_fare = original_price). (2) extract_fare_summary_booking max_steps 12 → 16; instruction updated to use minimal steps to dismiss popup then extract.

---

## 4. Implemented optimizations

### 4.1 Fare breakdown and convenience_fee reuse

- **Behavior:** Only the **first** flight’s session does the full payment-page flow (fill_traveler_proceed → extract_fare_breakdown). Other flights get `fare_breakdown` from the **booking page** (extract_fare_summary_booking); their `convenience_fee` is set from the first offer’s value so the breakdown is consistent.
- **Reason:** Convenience fee is typically similar per site; one payment-page extraction is enough.
- **Output:** First offer has full `fare_breakdown` (from payment page) and `additional_urls.payment`; later offers have `fare_breakdown` with base_fare, taxes, and the **reused** convenience_fee (and total_fare = base + taxes + convenience_fee).
- **Post-discount:** Every offer includes `best_price_after_coupon` = minimum of `price_after_coupon` across all coupons (or `None` if no coupons).

---

## 5. Other optimization options (documented, not yet implemented)

**Coupon extraction:** We do **not** reuse coupon extraction across flights; each offer gets its own coupon list from its itinerary/booking page (coupons can differ per flight/route).

### 5.1 Time filter in URL (checked — not available)

We checked whether Cleartrip's flight results page supports a **departure time-of-day** (e.g. Morning / Evening) filter in the URL, so we could skip the TIMINGS checkbox clicks in Phase 1.

- **Consumer site** (`www.cleartrip.com/flights/results?from=...&to=...&depart_date=...`): Documented and observed query params are `from`, `to`, `depart_date`, `adults`, `childs`, `infants`, `class`, `intl`, `sd`, `stops`. No `time`, `timing`, `departure_time`, or similar param is documented or visible in the API/reference docs.
- **Cleartrip API (saasdoc.cleartrip.com):** Search-flights reference does not list a departure-time filter in the request; departure time appears in *response* data (e.g. in fare keys), not as a request filter.
- **Conclusion:** Time-window filtering stays in the UI: we use the existing **TIMINGS** checkboxes (Early morning, Morning, etc.) via `extract_with_filter` / `_departure_window_to_checkboxes`. If Cleartrip adds a URL param for this in the future, we can add it in `_build_search_url` and switch to extraction-only in Phase 1.

**Inspected live URL** (Cleartrip results page, BLR→HYD, 11/03/2026):

`?adults=1&childs=0&infants=0&class=Economy&depart_date=11/03/2026&from=BLR&to=HYD&intl=n&origin=BLR%20-%20Bengaluru,%20IN&destination=HYD%20-%20Hyderabad,%20IN&sft=&sd=1772897267533&rnd_one=O&isCfw=false&isFF=false&isMultiFare=false&sourceCountry=Bengaluru&destinationCountry=Hyderabad&isFFSC=false&nonStop=`

| Param | Value | Note |
|-------|--------|------|
| from, to, depart_date, class, adults, childs, infants, intl | (same as we use) | Core search; we already set these. |
| origin, destination | Display strings (e.g. "BLR - Bengaluru, IN") | Optional; we omit and rely on from/to. |
| sft | (empty) | Unknown; could be sort/filter. No time value seen. |
| sd | 1772897267533 | Epoch-ms timestamp (cache/session); we use `sd=1`. |
| rnd_one, isCfw, isFF, isMultiFare, sourceCountry, destinationCountry, isFFSC | O / false / strings | UI/feature flags; we omit. |
| nonStop | (empty) | When present and set (e.g. nonStop=1), may mean non-stop only; we use `stops=0` for that. |

No **time-of-day** or **departure time** parameter appears in this URL; TIMINGS filtering remains UI-only.

---

| # | Option | Idea | Approx. saving | Effort |
|---|--------|------|----------------|--------|
| 2 | **Config flag to skip fare breakdown** | When caller does not need breakdown (e.g. “coupons only”), skip Steps 4–5 for all flights. | 0 or ~3m 30s | Low |
| 3 | **Combine fill traveler + extract fare** | Single instruction: fill details → skip add-ons → extract fare; one act instead of two. | One act + steps | Medium |
| 4 | **offers_top_n = 1 for “quick” mode** | When speed matters, analyze only the single cheapest flight. | ~3 min | Low |
| 6 | **Tighten max_steps** | Reduce `max_steps` for fill_traveler_proceed / select_fare_extract_coupons if logs show agent usually finishes earlier. | Fail faster on bad flows | Low |

---

## 6. Config reference (relevant parts)

- **offers_top_n:** 2 — number of flights for which Phase 3 runs.
- **use_parallel_offers:** true — Phase 3 runs harvest only in the main session; then 2 parallel Nova Act sessions (first with full flow to payment, second coupons-only) (see §8).
- **max_parallel_offers:** 2 — max concurrent sessions when use_parallel_offers is true.
- **Steps:** `book_flight`, `select_fare_continue_only`, `extract_coupons_from_booking_page`, `select_fare_extract_coupons`, `fill_traveler_proceed`, `extract_fare_breakdown`, `extract_fare_summary_booking` (see `backend/agents/cleartrip/config.yaml`).
- **fill_traveler_proceed:** max_steps 25; instruction uses phone `1234567890`, email `test@farewise.com`. Preceded by **skip_addons_first** (max_steps 12) when doing payment-page flow.

---

## 7. Test

- **Run:** `python tests/test_cleartrip_agent.py` from `backend/` (with venv and Nova Act env).
- **Validation:** Phase 1 (raw flights), Phase 2 (filtered list), Phase 3 (offers: coupons, fare_breakdown, itinerary and payment URLs). First offer has full fare_breakdown from payment page; others have fare_breakdown with reused convenience_fee.

---

## 8. Parallel Phase 3 (default)

**Config:** `use_parallel_offers: true`, `max_parallel_offers: 2`, `offers_top_n: 2` in `config.yaml`. Phase 3 harvests URLs in the main session, then runs N Nova Act sessions in parallel.

**Idea:** After normalization we have the list of desired (filtered) flights. Instead of doing “Book → coupons → traveler → fare” fully in sequence for each flight in one session, we can:

1. **Phase A — Harvest itinerary URLs (one session, sequential):**  
   In the same Nova Act session as today: for each of the top N flights, do only **Book → Select fare (Continue)** so the browser lands on the **itinerary/booking page**. Capture **itinerary_url** (e.g. `nova.page.url`), then **navigate back** to the search results and repeat for the next flight. Do **not** extract coupons or fill traveler in this phase.  
   Output: a list of **N itinerary URLs** (and a mapping flight_index / flight_key → URL).

2. **Phase B — Extract details in parallel (multiple Nova Act sessions):**  
   Start **K separate Nova Act sessions** (K = N, or e.g. 2 if you want to cap concurrency). Each session:
   - Starts with **`starting_page=itinerary_url`** (one of the harvested URLs).
   - Runs only: **extract coupons** (View All → extract list) + **extract fare summary (booking page)**. No Book, no fill traveler.
   - Returns: `coupons`, `fare_breakdown` (booking), `best_price_after_coupon` for that flight.  
   Optionally, **one** of the sessions (e.g. for the first flight) also does **fill traveler + skip add-ons → payment page → extract fare breakdown** so you get one full payment-page breakdown and `payment_url`.

3. **Merge:** Match each parallel result back to the flight (by URL or by index). Attach coupons, fare_breakdown, best_price_after_coupon, and payment_url (if present) to the right offer.

**Why this helps:**  
- Phase A is relatively short per flight (Book + Continue only).  
- Phase B runs in **parallel** across flights, so total time is dominated by the **slowest** of the K sessions instead of the **sum** of all of them.  
- You still get coupons and fare summary (and optionally one full payment breakdown) for every desired flight.

**Requirements / caveats:**  
- **Multiple concurrent Nova Act sessions:** Each `Workflow` + `NovaAct` pair is a separate browser/session. You’d run K such pairs (e.g. via `concurrent.futures.ThreadPoolExecutor` or `asyncio`), each with `starting_page=<itinerary_url>`. Confirm from Nova Act docs/runtime that multiple concurrent sessions are supported (e.g. rate limits, IAM, or process limits).

**Harvest-only main, then 2 parallel with flags:** The main session does **only** harvest: Book → Continue for flight 1, capture URL1; then navigate back, Book → Continue for flight 2, capture URL2. It returns a list of `{flight, itinerary_url}`. No extraction runs in the main session. The caller submits one parallel task per harvested URL; each task runs `_extract_offers_from_itinerary_url(..., do_payment_fare=(idx == 0))`, so the first flight gets full flow to payment page, the second gets coupons-only. Each URL is opened once (in its parallel session).

**Multiple Chrome instances:** Each `Workflow` + `NovaAct(..., starting_page=url)` creates a **new** browser session. So we have 1 main (harvest only) + 2 parallel (extraction). The Nova Act SDK does not expose "same browser, new tab"; parallel extraction uses multiple Chrome instances.  
- **Stability of itinerary URLs:** The harvested URL must be enough to open the booking page in a new session and see the same offer.  
- **Mapping back:** Index with each URL so Phase B results merge into the correct offer.

**Implemented:**  
- `_harvest_itinerary_urls(nova, items, search_url, on_url_harvested)` — harvest only; for each flight appends `{flight, itinerary_url}` and calls `on_url_harvested(idx, flight, url)`; returns `harvested` (list).  
- Caller submits `_extract_offers_from_itinerary_url(..., do_payment_fare=(idx == 0))` per URL; idx 0 = full flow, idx 1 = coupons-only.  
- `_extract_offers_from_itinerary_url(itinerary_url, flight_info, do_payment_fare)` — new Workflow + NovaAct, opens URL; runs extract_coupons + extract_fare_summary_booking; if `do_payment_fare`, then skip_addons_first, fill_traveler_proceed, extract_fare_breakdown.  
- After merging, `_apply_convenience_fee_from_first(offers_analysis)` sets convenience_fee (and total_fare) for non-first offers.

---

## 9. What is finally returned (detailed)

The agent’s `search()` returns a single object. When `fetch_offers=True`, it includes `flights` and `offers_analysis`. When `fetch_offers=False`, only `flights` is present.

### Top-level keys

| Key | Type | Description |
|-----|------|-------------|
| `flights` | `list[dict]` | All flights from Phase 1 (filtered by Phase 2): departure, arrival, airline, price, etc. |
| `offers_analysis` | `list[dict]` | One entry per “offer” (top N flights analyzed in Phase 3). Only present when `fetch_offers=True`. |

### `flights[]` (each item)

- **Source:** Phase 1 extraction + Phase 2 normalization (departure_window, max_stops, sort, dedup).
- **Typical keys:** `airline`, `flight_number`, `departure_time`, `arrival_time`, `duration`, `price`, `stops`, `departure_airport`, `arrival_airport`, `travel_class`, and any other fields defined by the extractor schema. These are the **candidate** flights the user can choose from; they are **not** per-offer coupon/fare details.

### `offers_analysis[]` (each item)

Each element corresponds to one of the top N flights (by price) that were analyzed for coupons and fare. Order matches the harvest order (first flight first, then second, etc.).

| Key | Type | Description |
|-----|------|-------------|
| `flight_number` | str | Flight number (e.g. `"6E-1234"`). |
| `airline` | str | Airline name/code. |
| `original_price` | int | Listed price (₹) from the results page. |
| `fare_type` | str | e.g. `"VALUE"` (from fare selection). |
| `coupons` | list | Coupons extracted from the booking page (View All). Each coupon: `code`, `description`, `discount` (₹), `price_after_coupon`. |
| `fare_breakdown` | dict | **First offer:** from payment page: `base_fare`, `taxes`, `convenience_fee`, `total_fare` (and any other keys from extract_fare_breakdown schema). **Other offers:** from booking-page summary + reused `convenience_fee` from first; may include `base_fare`, `taxes`, `total_fare`. |
| `best_price_after_coupon` | int \| None | Minimum of `price_after_coupon` across `coupons`, or `None` if no coupons. |
| `additional_urls` | dict | `itinerary`: itinerary/booking page URL for this offer. **First offer only:** `payment`: URL of the payment/checkout page (after fill traveler). |
| `error` | str | Present only if extraction failed for this offer (e.g. act timeout, exception). Other keys may still be partially filled. |

### Summary

- **Main session:** Harvest only (Book → Continue for top N; capture URLs). No extraction.
- **First offer (index 0):** Extracted in a **parallel** session with `do_payment_fare=True`: coupons, booking fare summary, skip add-ons, fill traveler, payment-page fare breakdown. Has the most complete `fare_breakdown` and the only `additional_urls.payment`.
- **Other offers (index ≥ 1):** Extracted in **parallel** sessions with `do_payment_fare=False`: coupons + booking fare summary only; `convenience_fee` (and possibly `total_fare`) are applied from the first offer via `_apply_convenience_fee_from_first`.
- **Convenience fee:** Only the first flight’s parallel session runs the full flow to the payment page and sees the real convenience fee; that value is reused for other offers.
