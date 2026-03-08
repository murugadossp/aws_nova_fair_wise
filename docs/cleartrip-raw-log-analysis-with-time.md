# Cleartrip Agent — Raw Log Analysis (with Time)

Run: **2026-03-07**, test `./run_agent.sh cleartrip` (Bengaluru→Hyderabad, 2026-03-11, departure 07:00–10:00, max_stops=0).

---

## 1. Wall-Clock Timeline

| Time (local)     | Elapsed | Event |
|------------------|---------|--------|
| **22:42:01.257** | 0:00    | Test start; Phases P1=P2=P3; filters: departure_window 07:00–10:00, max_stops=0, sort_by=departure |
| 22:42:01.257     | 0:00    | `CleartripAgent.search()` — Nova Act browser start |
| 22:42:02.974     | 0:02    | Workflow definition created/reused: farewise-cleartrip |
| **22:42:06.119** | 0:05    | Workflow run created: `019cc948-ee44-7f3e-a868-e79a6d350f69` (main session) |
| 22:42:06.119     | 0:05    | **Session 2a89** start on results URL (`.../results?from=BLR&to=HYD&depart_date=11/03/2026&...&stops=0`) |
| **22:42:20.034** | 0:19    | Combined filter+extract act starts (departure=Early morning, Morning; arrival=—) |
| …                | …       | Agent: scroll left sidebar → TIMINGS → click Early morning, Morning → extract flight cards → return 6 flights |
| **22:43:01.164** | **0:60**| **Phase 1 done.** Cleartrip returned 6 flights. Act reported **⏱️ 40.3s** |
| 22:43:01.164     | 1:00    | **Harvest [1/2]** Air India Express IX-2935 ₹7440 — Book act starts |
| …                | …       | Book act: scroll to card, click Book → **⏱️ 19.1s** |
| …                | …       | Select fare continue only → **⏱️ 22.0s** |
| **22:43:43.642** | **1:42**| **Harvest [1/2] URL captured** (IX-2935 itinerary). Harvest [2/2] starts |
| 22:43:43.643     | 1:42    | **Harvest [2/2]** IndiGo 6E-886 ₹7441 — Book act |
| …                | …       | Book → **⏱️ 12.6s**; Select fare continue → **⏱️ 17.1s** |
| **22:44:22.071** | **2:21**| **Harvest [2/2] URL captured** (6E-886 itinerary). All harvests done. |
| 22:44:24.848     | 2:23    | Parallel workflow run created: `019cc94b-0c49-7755-8fbe-655a5e351464` (flight 1) |
| 22:44:24.913     | 2:23    | Parallel workflow run created: `019cc94b-0c82-7a84-8d8a-aa0b39372d43` (flight 2) |
| 22:44:24.848     | 2:23    | **Session 4a33** start on flight 1 itinerary URL (do_payment_fare=True) |
| 22:44:24.913     | 2:23    | **Session 0277** start on flight 2 itinerary URL (do_payment_fare=False) |
| …                | …       | **4a33:** extract_coupons_from_booking_page → **⏱️ 29.7s** |
| …                | …       | **0277:** extract_coupons_from_booking_page → **⏱️ 26.8s** |
| …                | …       | **4a33:** extract_fare_summary_booking (dialog dismiss + scroll + extract) → **⏱️ 1m 1.6s** |
| …                | …       | **0277:** extract_fare_summary_booking (same) → **⏱️ 1m 7.5s** |
| **22:46:18.186** | **4:17**| **Session 0277 end.** Total in session: **1m 34.4s** across 2 act calls. Workflow SUCCEEDED |
| …                | …       | **4a33:** skip_addons_first → **⏱️ 34.3s** |
| …                | …       | **4a33:** fill_traveler_proceed (contact + traveler + continue to payment) → **⏱️ 55.1s** |
| …                | …       | **4a33:** extract_fare_breakdown (payment page) → **⏱️ 5.9s** |
| **22:47:47.779** | **5:46**| **Session 4a33 end.** Total in session: **3m 6.6s** across 5 act calls. Workflow SUCCEEDED |
| **22:47:49.417** | **5:48**| **Main session 2a89 end.** Total in session: **1m 51.2s** across 5 act calls. Workflow SUCCEEDED |
| 22:47:49.417     | 5:48    | Phase 1: 6 raw flights listed; Phase 2: FlightNormalizer 6→4; Phase 3: 2 offers validated |
| 22:47:49.421     | 5:48    | test_cleartrip_search PASSED; Cleartrip agent test DONE |

**Total wall-clock (run start → test DONE): ~5 min 48 s.**

---

## 2. Per-Session Act Times (Approx. Time Worked)

### Main session (2a89) — 5 acts, 1m 51.2s total

| Step | Instruction / role | Approx. time |
|------|--------------------|--------------|
| 1 | extract_with_filter (TIMINGS + extract flight cards) | **40.3s** |
| 2 | book_flight (IX-2935 ₹7440) | 19.1s |
| 3 | select_fare_continue_only | 22.0s |
| 4 | book_flight (6E-886 ₹7441) | 12.6s |
| 5 | select_fare_continue_only | 17.1s |

### Parallel session 4a33 (flight 1 — IX-2935, full payment flow) — 5 acts, 3m 6.6s total

| Step | Instruction / role | Approx. time |
|------|--------------------|--------------|
| 1 | extract_coupons_from_booking_page | **29.7s** |
| 2 | extract_fare_summary_booking (booking page; dialog dismiss + scroll) | **1m 1.6s** |
| 3 | skip_addons_first | 34.3s |
| 4 | fill_traveler_proceed | 55.1s |
| 5 | extract_fare_breakdown (payment page) | 5.9s |

### Parallel session 0277 (flight 2 — 6E-886, coupons + booking fare only) — 2 acts, 1m 34.4s total

| Step | Instruction / role | Approx. time |
|------|--------------------|--------------|
| 1 | extract_coupons_from_booking_page | **26.8s** |
| 2 | extract_fare_summary_booking (booking page; dialog dismiss + scroll) | **1m 7.5s** |

---

## 3. Phase Summary with Time

| Phase | What | Start (elapsed) | End (elapsed) | Duration (approx) |
|-------|------|-----------------|---------------|-------------------|
| **P1** | Filter + extract 6 flights (main session) | 0:00 | 1:00 | **~1 min** |
| **Harvest** | Book + Continue × 2 (main session) | 1:00 | 2:21 | **~1 min 21 s** |
| **Parallel** | Two workers: coupons + fare summary; flight 1 also skip add-ons + traveler + payment fare | 2:23 | 5:46 | **~3 min 23 s** (wall; longest worker 4a33 = 3m 6.6s) |
| **Post** | Normalizer + validation (in-process) | 5:47 | 5:48 | **&lt;1 s** |

---

## 4. Bottlenecks (from this run)

1. **extract_fare_summary_booking** (both workers): **~1m 1.6s** and **~1m 7.5s**. Most of that is struggling to dismiss the “Apply coupon or gift card” dialog (click outside, scroll, retry). One worker eventually closes via “View All” click; the other via scroll up and extract.
2. **extract_with_filter**: **40.3s** — scroll sidebar, click 2 checkboxes, extract cards. Reasonable.
3. **fill_traveler_proceed** (flight 1 only): **55.1s** — contact + traveler + continue to payment. Dominant part of flight-1-only work.
4. **skip_addons_first**: **34.3s** — find and click Skip add-ons + confirmation.

---

## 5. Raw Log Snippets (timestamp + message)

```
2026-03-07 22:42:01.257  INFO  __main__  test_cleartrip_search  === test_cleartrip_search: Bengaluru→Hyderabad date=2026-03-11 ===
2026-03-07 22:42:01.257  INFO  __main__  test_cleartrip_search  Phases: P1=True  P2=True  P3=True  filters={'departure_window': ['07:00', '10:00'], 'max_stops': 0, 'sort_by': 'departure'}
2026-03-07 22:42:01.257  INFO  agents.cleartrip.agent  search  Searching Cleartrip: Bengaluru→Hyderabad date=2026-03-11 class=economy fetch_offers=True
2026-03-07 22:42:06.119  INFO  nova_act.types.workflow  __enter__  Created workflow run 019cc948-ee44-7f3e-a868-e79a6d350f69 with model nova-act-latest
2026-03-07 22:42:20.034  INFO  agents.cleartrip.agent  search  Combined filter+extract: departure=['Early morning', 'Morning'] arrival=[] (single act)
2026-03-07 22:43:01.164  INFO  agents.cleartrip.agent  search  Cleartrip returned 6 flights for Bengaluru→Hyderabad on 2026-03-11
2026-03-07 22:43:01.164  INFO  agents.cleartrip.agent  _harvest_itinerary_urls  Harvest [1/2]: Air India Express IX-2935 ₹7440
2026-03-07 22:43:43.642  INFO  agents.cleartrip.agent  _harvest_itinerary_urls  Harvest [1/2]: Air India Express IX-2935 → https://www.cleartrip.com/flights/itinerary/NIAHb9883dce-7da...
2026-03-07 22:43:43.643  INFO  agents.cleartrip.agent  _harvest_itinerary_urls  Harvest [2/2]: IndiGo 6E-886 ₹7441
2026-03-07 22:44:22.071  INFO  agents.cleartrip.agent  _harvest_itinerary_urls  Harvest [2/2]: IndiGo 6E-886 → https://www.cleartrip.com/flights/itinerary/NIAH630d0f8b-fa7...
2026-03-07 22:44:24.848  INFO  nova_act.types.workflow  __enter__  Created workflow run 019cc94b-0c49-7755-8fbe-655a5e351464 with model nova-act-latest
2026-03-07 22:44:24.913  INFO  nova_act.types.workflow  __enter__  Created workflow run 019cc94b-0c82-7a84-8d8a-aa0b39372d43 with model nova-act-latest
2026-03-07 22:46:18.186  INFO  nova_act.types.workflow  __exit__   Updated workflow run 019cc94b-0c49-7755-8fbe-655a5e351464 status to 'SUCCEEDED'
2026-03-07 22:47:47.779  INFO  nova_act.types.workflow  __exit__   Updated workflow run 019cc94b-0c82-7a84-8d8a-aa0b39372d43 status to 'SUCCEEDED'
2026-03-07 22:47:49.417  INFO  nova_act.types.workflow  __exit__   Updated workflow run 019cc948-ee44-7f3e-a868-e79a6d350f69 status to 'SUCCEEDED'
2026-03-07 22:47:49.417  INFO  __main__  test_cleartrip_search  Phase 1: Agent extracted 6 raw flights
2026-03-07 22:47:49.419  INFO  nova.flight_normalizer  normalize  FlightNormalizer: 6 raw results, filters={'departure_window': ['07:00', '10:00'], 'max_stops': 0, 'sort_by': 'departure'}
2026-03-07 22:47:49.419  INFO  nova.flight_normalizer  _apply_filters  Filter max_stops=0: 6 → 6 flights
2026-03-07 22:47:49.419  INFO  nova.flight_normalizer  _apply_filters  Filter departure_window 07:00–10:00: 6 → 4 flights
2026-03-07 22:47:49.419  INFO  nova.flight_normalizer  normalize  FlightNormalizer: 4 final flights (from 6 raw)
2026-03-07 22:47:49.421  INFO  __main__  test_cleartrip_search  test_cleartrip_search PASSED  (raw=6, filtered=4, offers=2)
2026-03-07 22:47:49.421  INFO  __main__  <module>  Cleartrip agent test DONE
```

---

## 6. Session IDs (this run)

| Short ID | Session ID (suffix) | Role |
|----------|----------------------|------|
| 2a89 | 019cc948-f1d9-7b01-9caa-049185042a89 | Main: results page → filter+extract → harvest [1/2] → harvest [2/2] |
| 4a33 | 019cc94b-0ddc-7fd8-8059-325f2ec94a33 | Parallel worker 1: IX-2935 itinerary; coupons + booking fare + skip add-ons + fill traveler + payment fare |
| 0277 | 019cc94b-0d9d-7126-afc9-f182ad280277 | Parallel worker 2: 6E-886 itinerary; coupons + booking fare only |

Workflow run IDs: main `019cc948-ee44-7f3e-a868-e79a6d350f69`; workers `019cc94b-0c49-...` (flight 1), `019cc94b-0c82-...` (flight 2).

---

## 7. Summary

- **Total run time:** ~5 min 48 s (22:42:01 → 22:47:49).
- **Phase 1:** ~1 min (one combined filter+extract act, 40.3s agent time).
- **Harvest:** ~1 min 21 s (two Book + Continue cycles in main session).
- **Parallel:** Both workers start after harvest; worker 2 finishes in ~1m 34s (2 acts); worker 1 in ~3m 7s (5 acts). Wall-clock parallel segment ~3m 23s.
- **Largest single-act cost:** extract_fare_summary_booking (~1m–1m 7s each) due to coupon-dialog dismissal; then fill_traveler_proceed (55.1s) and skip_addons (34.3s) on flight 1.
