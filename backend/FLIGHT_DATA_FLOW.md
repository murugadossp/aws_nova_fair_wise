# FareWise Data Pipeline

This document outlines the end-to-end data flow for flight processing in FareWise, specifically highlighting the optimizations implemented for Ixigo and Cleartrip.

## Changelog

### 2026-03-15 (iteration 2) — Fix: "Finding offers" badge still not appearing — wrong root cause identified

**Problem:** Even after the previous fix (adding `updateInterimCardsWithScope`), the ⏳ badge and fare breakdown spinner were still not showing on interim cards.

**True root cause — message ordering in orchestrator:** The previous fix assumed `coupon_analysis_scope` arrived *after* `agent_phase`. In reality it arrived *much later* — only after `asyncio.gather()` finished all of Phase 3. By then, `offer_extracted` messages had already run `updateInterimCard()` which finalises cards (solid border + fare breakdown). So `updateInterimCardsWithScope` was adding badges to already-final cards, or being skipped by the guard.

The actual message order before fix:
```
agent_phase              → renderInterimResults (couponAnalysisFlights empty → no badge, no spinner)
offer_extracted × N      → updateInterimCard (adds fare breakdown, finalises card)
coupon_analysis_scope    → updateInterimCardsWithScope (too late — cards already done)
```

**Fix (`orchestrator.py`):** Moved `coupon_analysis_scope` emission into the `on_progress("phase2_start")` callback, queued via `run_coroutine_threadsafe` *immediately before* `agent_phase`. Both are queued to the same event loop FIFO, so the frontend processes scope first, then renders interim cards with the set already populated.

New message order:
```
coupon_analysis_scope    → couponAnalysisFlights populated {"ixigo-6E537", ...}
agent_phase              → renderInterimResults sees non-empty set → isSearchingCoupons=true → ⏳ badge + spinner shown
offer_extracted × N      → updateInterimCard removes badge, adds Base/Taxes/Conv.Fee breakdown
results                  → renderResults shows final cards
```

**Secondary fix (`sidepanel.html`):** Added guard in `updateInterimCardsWithScope` — skips cards whose `borderStyle === 'solid'` (already finalised by `updateInterimCard`) to prevent the legacy post-gather `coupon_analysis_scope` from re-adding stale badges.

**Changed files:**
- `backend/agents/orchestrator.py` — moved `coupon_analysis_scope` send inside `on_progress("phase2_start")` callback, before `agent_phase`; removed the post-`asyncio.gather()` send
- `frontend_chrome_extension/sidepanel/sidepanel.html` — added finalised-card guard in `updateInterimCardsWithScope`

### 2026-03-15 (iteration 1) — Fix: "Finding offers" badge and fare breakdown spinner not showing during Phase 1

**Problem:** When flight cards were rendered during Phase 1 (interim results), the "⏳ Finding best offers..." badge and "Extracting coupon offers..." spinner were never displayed — cards just appeared at low opacity with no loading feedback.

**Root cause (first diagnosis):** `renderInterimResults()` in `sidepanel.html` is called when the `agent_phase` WebSocket message arrives. At that point, `couponAnalysisFlights` was still empty. The condition `couponAnalysisFlights.size === 0 ? false : ...` treated an empty set as "no flights need analysis", so `isSearchingCoupons` was always `false`.

**Fix (`sidepanel.html`):** Added `updateInterimCardsWithScope(flightIds)` function called when `coupon_analysis_scope` arrives, to retroactively patch already-rendered cards with the badge and spinner.

**Changed files:**
- `frontend_chrome_extension/sidepanel/sidepanel.html` — new `updateInterimCardsWithScope()` function; `coupon_analysis_scope` message handler now calls it after populating the set

---

## Key Recent Change (Mar 15, 2026)

**Offer Extraction Extended from Top 2 → Top 5 Flights**

Previously, only the top 2 cheapest flights went through offer extraction (Phase 3), leaving secondary flights with no fare breakdown data in the UI. Now:

- **All 5 filtered flights** are processed through offer extraction to get detailed fare breakdown (base fare, taxes, convenience fee)
- **Only top 2 flights** are sent to Nova Pro (Phase 4) for coupon analysis — coupon extraction is expensive and only valuable for the cheapest options
- **Result:** Secondary flights (3-5) now display complete fare breakdown without coupon analysis, eliminating blank breakdown rows in the UI
- **Trade-off:** Offer extraction takes ~2.5x longer per search (5 booking pages navigated in parallel vs 2)

This ensures data completeness while maintaining reasonable performance.

## 1. Extraction (Phase 1)
**Component:** `Agent.search()` (e.g., `IxigoAgent`)
**Goal:** Extract as many raw flights as possible from the search results page to give the Normalizer a wide pool to filter.
*   **Action:** The Nova Act model scrolls through the frontend results.
*   **Constraint:** The instruction file (e.g., `wait_and_extract.md`) asks the model to extract up to **10** flights as they become visible.
*   **Output:** An unstructured list of dictionary results (raw data).

## 2. Normalization & Filtering (Phase 2)
**Component:** `FlightNormalizer.normalize()`
**Goal:** Clean the data, apply user filters (e.g., stops, departure time), sort by cheapest, and aggressively cap the output to avoid UI clutter and token bloat.
*   **Action:** 
    1. Converts all raw flights to a canonical schema.
    2. Drops invalid records (missing price or airline).
    3. Deduplicates identical flights (same airline, flight number, departure time) keeping only the lowest price.
    4. Applies user filters strictly (e.g., `stops=0`). Flights failing the filter are instantly dropped.
    5. Sorts the remaining flights by price (ascending).
    6. **Optimization:** Caps the final array to **Top 5**.
*   **Output:** The `filtered` array containing exactly 5 clean, sorted flights.

## 3. Offer Extraction (Phase 3)
**Component:** `Agent.fetch_offers()` (e.g., parallel Nova Act sessions)
**Goal:** Automate the booking flow to extract platform-specific coupons, discounts, and detailed fare breakdown.
*   **Optimization:** Running this flow takes time (15-30s per flight), so it is limited to a configurable subset.
*   **Constraint:** The agent reads `offers_top_n` from its `config.yaml` (Ixigo/Cleartrip: 5) and slices the target array (`targets = filtered[:5]`).
*   **Action:** Nova Act simulates clicking "Book" for the top 5 flights in parallel, scrapes the checkout/booking page for:
    - **Flights 1-5:** Base fare, taxes, convenience fee, and total price
    - **Flights 1-2:** Also extracts valid coupons and card-specific discounts
*   **Output:** The `offers_analysis` array containing full fare breakdown for flights 1-5, plus coupon details for top 2.

## 4. Final Reasoning (Nova Pro) — Coupon Analysis
**Component:** `TravelOrchestrator._run_agent` -> `NovaReasoner.calculate_best_flight()`
**Goal:** Apply the user's selected credit cards to the Top 2 analyzed flights, perform math to deduce the final effective price with best coupon, pick a definitive winner, and generate human-readable explanation.
*   **Optimization:** Sending all flights to the LLM consumes excessive tokens and risks model truncation; coupon analysis is only valuable for the cheapest options.
*   **Action:** The Orchestrator intercepts the payload and passes *only* the Top 2 flights (`flights[:2]`) to Nova Pro for coupon reasoning.
*   **Nova Pro Constraint:** The prompt explicitly forces the LLM to return `all_results` at the exact length it received (2) without truncating.
*   **Output:** A JSON structure containing the `winner` (Top 1 flight with best coupon applied), pricing breakdown, and `reasoning` text for Top 2 flights only.

## 5. Failsafe Re-Injection & Display
**Component:** `TravelOrchestrator.run()`
**Goal:** Ensure the user sees all 5 flights with fare breakdown, even though only 2 were analyzed for coupons.
*   **Action:**
    1. The Orchestrator merges results from Phase 3 (offer extraction with fare details for flights 1-5) and Phase 4 (coupon reasoning for flights 1-2).
    2. Flights 3-5: Receive coupon analysis results (`offers = null`), but carry their full fare breakdown from Phase 3.
    3. The Orchestrator compares original 5 flights to 2 returned by Nova Pro, identifies missing 3, dynamically injects them back.
*   **Fallback Fields:**
    - Flights 3-5: `price_effective = flight.price`, `saving = 0`, `card_used = null` (no coupon analysis)
    - But: `offers.fare_details` is populated from Phase 3 (base_fare, taxes, convenience_fee)
*   **Output:** The final WebSocket payload contains all 5 flights:
    - **Flights 1-2:** Full coupon analysis + best price recommendation + detailed fare breakdown
    - **Flights 3-5:** Fare breakdown only (no coupon analysis) labeled as "Secondary flights"
    - **UI:** Winner badge on Flight 1, coupon badges on Flights 1-2, fallback "Total price" row on Flights 3-5
