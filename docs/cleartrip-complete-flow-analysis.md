# Cleartrip Agent — Complete Flow Analysis

End-to-end flow from user/planner input to final structured results (flights + offers).

---

## 1. Entry Points

| Entry | Where | What |
|-------|--------|------|
| **Test** | `backend/tests/test_cleartrip_agent.py` | Calls `CleartripAgent().search(...)` with fixed filters; then applies `FlightNormalizer` on raw flights; validates Phase 1–3. |
| **Orchestrator** | `backend/agents/orchestrator.py` + `backend/main.py` | `TravelPlanner.plan(query)` → structured plan (route, filters, agents) → `CleartripAgent().search(...)` → `FlightNormalizer.normalize(...)` → combined response. |

Filters (e.g. `departure_window`, `arrival_window`, `max_stops`, `sort_by`) come from the planner when using the orchestrator, or from the test/config when running the test directly.

---

## 2. High-Level Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  INPUT: from_city, to_city, date, travel_class, filters, fetch_offers           │
└─────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  PHASE 1 (Agent — single Nova Act session)                                       │
│  • Build search URL (from/to/date/class/stops)                                   │
│  • Open results page                                                             │
│  • Apply time filters (if any) + extract ALL flight cards → raw list             │
└─────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  PHASE 2 (Test/Orchestrator — Python only)                                       │
│  • FlightNormalizer: canonical schema, dedup, apply filters, sort                │
│  • Output: filtered list (used for display + for Phase 3 source list)             │
└─────────────────────────────────────────────────────────────────────────────────┘
                                          │
                          fetch_offers=True?
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    │ YES                                       │ NO
                    ▼                                           ▼
┌───────────────────────────────────────┐         Return { flights, offers_analysis }
│  PHASE 3 — Offers for top N flights    │         (or just flights if no offers)
│  (N = offers_top_n, default 2)        │
└───────────────────────────────────────┘
                    │
    use_parallel_offers?
                    │
    ┌───────────────┴───────────────┐
    │ TRUE (default)                │ FALSE
    ▼                               ▼
 Harvest then parallel             Single-session sequential
 (see §4)                          (see §5)
```

---

## 3. Phase 1 — Search and Extract (One Nova Act Session)

**Session:** One `Workflow` + one `NovaAct`; starting URL = Cleartrip results page.

### 3.1 URL construction

- **Config:** `config.yaml` → `base_url`, `city_codes`, `class_codes`, `max_stops` from filters.
- **Logic:** `_build_search_url(base_url, from_code, to_code, date_ct, travel_class, filters)`.
- **Result:** e.g.  
  `https://www.cleartrip.com/flights/results?from=BLR&to=HYD&depart_date=11/03/2026&adults=1&childs=0&infants=0&class=Economy&intl=n&sd=1&stops=0`
- **Note:** Time-of-day (e.g. Morning/Evening) is **not** in the URL; it is applied via TIMINGS checkboxes in the UI.

### 3.2 Filter vs extract

- **If** `departure_window` or `arrival_window` is present **and** step `extract_with_filter` exists:
  - **Single act:** `extract_with_filter` (instruction = `site_adapter_cleartrip.md` + `extract_with_filter.md`).
  - **Behaviour:** Scroll left sidebar to TIMINGS → click checkboxes for “Taking off from {from_city}” and “Landing in {to_city}” → then extract all visible flight cards.
  - **Output:** One JSON array of flights (airline, flight_number, departure, arrival, duration, stops, price).
- **Else** (no time filter or combined step missing/failed):
  - Optionally **pre_filter** act: apply only TIMINGS checkboxes (no extraction).
  - Then **extraction** act: `site_adapter_cleartrip.md` + `extractor_prompt.md` → extract all flight cards (no filter clicks).

### 3.3 Result shaping

- Raw list from the act is turned into **result list** via `_build_results(...)`:
  - Each item gets: `platform: "cleartrip"`, `from_city`, `to_city`, `date`, `class`, plus extracted fields, and `url` = search URL.
- This list is **Phase 1 output**: “raw” flights (no dedup, no Python filters yet).

---

## 4. Phase 3 — Parallel Path (use_parallel_offers = true)

Used when `fetch_offers=True` and `use_parallel_offers=True` (default).

### 4.1 Which flights get offers

- **Source list:** `_filter_items_for_offers(items, filters)`:
  - Applies `max_stops`, `departure_window`, `arrival_window` in Python on the **raw** items (same logic as normalizer, but on the list that will be used only for offers).
- **Top N:** Sort by price, take first `offers_top_n` (default 2).
- So: offers are for the **top N cheapest flights within the same filters** (e.g. 2 cheapest morning non-stop flights).

### 4.2 Harvest (main session only)

- **Method:** `_harvest_itinerary_urls(nova, filtered_items, search_url)`.
- **Loop** for each of the top N flights (in price order):
  1. If index > 0: `nova.page.goto(search_url)` (back to results).
  2. **Book:** act from `book_flight.md` (find card for airline + flight_number + price, click “Book”).
  3. **Continue:** act from `select_fare_continue_only.md` (click “Continue” in fare dialog; VALUE is pre-selected).
  4. Read `nova.page.url` → **itinerary URL** (booking page).
  5. Append `{ "flight": flight, "itinerary_url": url }` to `harvested`.
- **No extraction** in the main session (no coupons, no fare summary here).
- **Output:** List of `{ flight, itinerary_url }` for the same top N flights.

### 4.3 Parallel extraction (new sessions)

- After **all** harvests are done, a `ThreadPoolExecutor(max_workers=max_parallel_offers)` runs.
- **One task per harvested flight:** `_extract_offers_from_itinerary_url(workflow_name, itinerary_url, flight_info, headless, do_payment_fare=(idx==0))`.
  - **idx == 0:** first flight (by price) → `do_payment_fare=True`.
  - **idx >= 1:** other flights → `do_payment_fare=False`.

**Each parallel session (one per flight):**

1. **New** `Workflow` + **new** `NovaAct`; `starting_page` = that flight’s **itinerary_url** (booking page).
2. **Extract coupons:** act from `extract_coupons_from_booking_page.md` (scroll right panel → “View All” → extract code, description, discount).  
   Then: `price_after_coupon = max(0, original_price - discount)`; `best_price_after_coupon = min(price_after_coupon)`.
3. **Booking-page fare:** act from `extract_fare_summary_booking.md` (dismiss coupon dialog if open; read right-side fare summary → base_fare, taxes, convenience_fee, total_fare).  
   Fills `fare_breakdown` for this flight (booking page only; convenience_fee may be 0 here).
4. **If do_payment_fare:**
   - Act `skip_addons_first.md` → skip add-ons.
   - Act `fill_traveler_proceed.md` → contact + traveler → continue to payment.
   - Act `extract_fare_breakdown.md` on **payment page** → base_fare, taxes, convenience_fee, total_fare.  
   Overwrites `fare_breakdown` and sets `additional_urls["payment"] = current URL`.

### 4.4 Convenience fee reuse

- **After** all parallel tasks complete: `_apply_convenience_fee_from_first(offers_analysis)`.
- Finds the first offer that has `fare_breakdown.convenience_fee` (typically the one that did payment flow).
- Overwrites every other offer’s `fare_breakdown.convenience_fee` with that value and recomputes `total_fare` where applicable so all offers show a consistent convenience_fee (and total) even when only one session went to payment.

### 4.5 Final Phase 3 output

- **offers_analysis:** list of dicts, one per top-N flight:
  - `flight_number`, `airline`, `original_price`, `fare_type`, `coupons`, `fare_breakdown`, `best_price_after_coupon`, `additional_urls` (itinerary + payment if applicable).
- Returned together with **flights** (the same raw list from Phase 1):  
  `{ "flights": results, "offers_analysis": offers_analysis }`.

---

## 5. Phase 3 — Sequential Path (use_parallel_offers = false)

Single Nova Act session; same tab for all top-N flights.

- For each of the top N (by price, after `_filter_items_for_offers`):
  1. If idx > 0: `nova.page.goto(search_url)`.
  2. **Book** → **select_fare_extract_coupons** (one act: Continue in fare dialog + open “View All” coupons + extract coupons).
  3. **First flight only:** skip_addons_first → fill_traveler_proceed → extract_fare_breakdown (payment page); store payment URL.
  4. **Other flights:** extract_fare_summary_booking (booking page only).
  5. Compute `price_after_coupon` and `best_price_after_coupon` per offer.
- `_apply_convenience_fee_from_first` is still applied so all offers get the same convenience_fee from the first flight’s payment page.

---

## 6. Phase 2 — FlightNormalizer (outside agent)

Applied by the **test** or **orchestrator** on `raw = agent.search(...)`.

- **Input:** `raw["flights"]` (or `raw` if it’s the list of flights).
- **Steps:**
  1. **Canonical schema:** map each item to standard fields; drop invalid (no price/airline). Rename e.g. `url` → `book_url`, `class` → `travel_class`.
  2. **Deduplication:** key = (airline, flight_number, departure); keep lowest price per key.
  3. **Structured filters:** `max_stops`, `departure_window`, `arrival_window` (inclusive HH:MM).
  4. **Sort:** by `sort_by` (price | departure | duration).
- **Output:** Filtered, sorted list in canonical schema. This is what the app shows as “filtered” flights and what the test uses to validate that offers correspond to filtered flights.

---

## 7. Config and Instructions Summary

| Config key | Role |
|------------|------|
| `offers_top_n` | Number of flights for which offers are fetched (default 2). |
| `use_parallel_offers` | If true → harvest then parallel sessions; if false → one session, sequential. |
| `max_parallel_offers` | Max concurrent workers (default 2). |
| `time_buckets` | Labels and HH:MM ranges for TIMINGS checkboxes (Early morning, Morning, …). |
| `steps.*` | Step name → instruction file(s), schema, max_steps. |

**Instruction files (steps) used in flow:**

- **Phase 1:** `extract_with_filter` (site_adapter + extract_with_filter), or `pre_filter` + `extraction` (site_adapter + extractor_prompt).
- **Harvest:** `book_flight`, `select_fare_continue_only`.
- **Parallel / sequential offers:** `extract_coupons_from_booking_page`, `extract_fare_summary_booking`, `skip_addons_first`, `fill_traveler_proceed`, `extract_fare_breakdown`.

---

## 8. Data Flow Summary

| Stage | Input | Output |
|-------|--------|--------|
| Agent Phase 1 | URL + filters (time checkboxes) | Raw flight list (with `url` = search URL). |
| _filter_items_for_offers | Raw items + filters | Top N by price within filters (used only for Phase 3). |
| Harvest | Main session + top N | List of { flight, itinerary_url }. |
| Parallel extract | itinerary_url per flight | Per-flight: coupons, booking fare_breakdown; first flight also payment fare_breakdown + payment URL. |
| _apply_convenience_fee_from_first | offers_analysis | Same list with convenience_fee (and total) aligned from first offer. |
| Agent return | — | `{ flights: raw_list, offers_analysis: [...] }`. |
| FlightNormalizer | raw flights + filters | Canonical, deduped, filtered, sorted list. |
| Test / app | Agent return + normalizer | Display: filtered list + offers_analysis; validation uses both. |

---

## 9. Important Details

- **Price-after-coupon:** Always `max(0, original_price - discount)`. `original_price` is the listing price for that flight; discount is from the coupon extraction (same card as code/description).
- **Fare breakdown source:** With parallel: first flight from **payment page** (after add-ons + traveler); others from **booking page** (then convenience_fee overwritten from first). With sequential: same idea in one session.
- **Harvest then parallel:** All itinerary URLs are collected in the main session before any parallel session starts, so there is no overlap between harvest and extract and no duplicate “open” of the first itinerary in the main session for extraction.
- **Failure handling:** If a harvest or parallel extract fails, that offer entry can still be appended with `error` and empty coupons/fare_breakdown; `_apply_convenience_fee_from_first` can still fill a minimal breakdown for others when the first has a valid convenience_fee.

This is the complete flow from user/planner input through Cleartrip agent, normalizer, and final flights + offers.
