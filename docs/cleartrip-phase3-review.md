# Cleartrip Phase 3 — Offers/Coupon Extraction — Review and Next Steps

Phase 3 runs after flight search and normalization: for the **top N cheapest** flights (by price), the agent clicks Book → Select fare (VALUE) → Continue, then extracts all coupons from the booking page and records the itinerary URL.

**Test run reviewed:** Bengaluru→Hyderabad, 2026-03-11, departure_window 07:00–10:00, max_stops=0, Phase 3 enabled (top 2 flights).

---

## What Worked

- **Combined filter+extract:** Single act for TIMINGS + extraction (~38.5s); 6 raw flights extracted.
- **Top-2 selection:** Correctly chose the two cheapest by price (IX-1756 ₹4351, IX-2935 ₹7032).
- **Itinerary URLs:** Both offers include `additional_urls.itinerary` with valid Cleartrip itinerary URLs.
- **Coupons:** Flight 1 had 4 coupons from the “View All” dialog; flight 2 eventually had 6. All entries have code, description, discount, and `price_after_coupon`.

---

## Issues Identified

### 1. Navigate-back (~23s overhead)

When returning to the search results URL for the second flight, the agent was given the instruction “Navigate to this URL: &lt;search_url&gt;”. Instead of using `goToUrl` immediately, it:

1. Closed the coupon popup (clicked “View All”).
2. Clicked the Cleartrip logo.
3. Then used `goToUrl`.

**Fix:** Use programmatic navigation (`nova.page.goto(search_url)`) from code for the second and subsequent flights so the agent is not used for this step.

### 2. Second-flight coupon extraction (~63.6s)

On the second booking page, the “View All” link was not in view initially. The agent:

- Clicked wrong elements (e.g. “Flat ₹843 off” coupon, CTDOM, “All offers” tab).
- Then scrolled and eventually found “View All” and extracted 6 coupons.

**Fix:** In the coupon-extraction prompt, instruct the agent to scroll the “Apply coupon or gift card” section so the bottom (and the “View All” link) is in view first, and to avoid clicking coupon cards or the “All offers” tab when the goal is to open the full list.

### 3. Minor

One coupon was returned as `BOBCC` while the agent’s reasoning mentioned “BOBC” (possible display vs code difference on the page).

---

## Timing Summary (Pre-fix Run)

| Step | Time |
|------|------|
| Filter + extract | 38.5s |
| Flight 1: Book | 20.0s |
| Flight 1: Continue | 15.6s |
| Flight 1: Coupons | 31.8s |
| **Navigate back** | **23.0s** |
| Flight 2: Book | 13.9s |
| Flight 2: Continue | 19.5s |
| Flight 2: Coupons | **63.6s** |
| **Total session** | **~3m 46s** (8 acts) |

---

## Fixes Applied (This Plan)

1. **Programmatic navigate-back:** In `_extract_offers_for_flights`, for `idx > 0`, use `nova.page.goto(search_url)` (and optional `wait_for_load_state`) instead of `nova.act("Navigate to this URL: ...")`.
2. **Coupon prompt:** In `extract_coupons.md`, add instructions to scroll the coupon section so “View All” is in view first, and not to click coupon cards or the “All offers” tab when opening the full list.

---

## Next Steps

### Immediate (this plan)

- [x] Document this review.
- [x] Implement programmatic navigate-back (Fix 1).
- [x] Update coupon extraction prompt (Fix 2).
- [x] Re-run Phase 3 and confirm timings/behavior.
- [x] Update this doc with new timings after the test run.

### Later iterations (optional)

- Consider reducing `max_steps` for the coupon act if the prompt still leads to long exploratory runs.
- Expose `offers_top_n` (and other Phase 3 knobs) from a global/config layer if product requirements change.
- Add an E2E test that asserts approximate act count or total duration for Phase 3 (e.g. one fewer act when using programmatic navigate-back).

---

## Post-fix Timings (2026-03-07 run)

After implementing programmatic navigate-back and the coupon prompt updates:

- **Act count:** 7 (was 8). The navigate-back step is no longer an agent act; the second flight uses `page.goto(search_url)` + `wait_for_load_state("domcontentloaded")` in code.
- **Total session:** ~3m 19s wall clock (pre-fix ~3m 46s). Savings from dropping the ~23s navigate-back act plus faster page load with programmatic goto.
- **Behavior:** Flight 1 and Flight 2 both completed; 4 and 6 coupons extracted; itinerary URLs present in `additional_urls` for both.

| Step | Time (approx) |
|------|----------------|
| Filter + extract | 40s |
| Flight 1: Book | ~19s |
| Flight 1: Continue | ~16s |
| Flight 1: Coupons | ~35s |
| Navigate back (programmatic) | &lt;5s |
| Flight 2: Book | ~14s |
| Flight 2: Continue | ~19s |
| Flight 2: Coupons | ~35s |
| **Total session** | **~3m 19s** (7 acts) |
