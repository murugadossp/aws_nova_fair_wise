# Cleartrip Todo

Updated after the fresh full Cleartrip wrapper run and architecture documentation pass.

## Remaining Todo

- [ ] Rerun the full Cleartrip wrapper test and compare probe timings after the refined coupon flow removed the redundant dialog handoff.

## Recently Completed

- [x] Refactor the payment probe in `backend/agents/cleartrip/agent.py` into screen-specific Nova acts.
- [x] Add dedicated payment-step instruction files for insurance, add-ons, popup, contact, and traveller flows.
- [x] Capture per-step payment telemetry and expose it in tests and final output.
- [x] Add a focused single-itinerary test in `backend/tests/test_cleartrip_itinerary.py`.
- [x] Refine coupon extraction so `View All` is optional and descriptions can include the supporting line before `Know more`.
- [x] Reload the itinerary URL before payment probing to avoid coupon-dialog state leakage in the focused flow.
- [x] Split the probe flight into parallel coupon and payment branches from the same harvested itinerary URL.
- [x] Add branch-level telemetry: coupon branch, payment branch, and parallel wall-clock timing.
- [x] Tighten payment prompts so visible payment fare summary / convenience fee is treated as a terminal condition and billing details should not be opened.
- [x] Run a fresh full Cleartrip wrapper flow and verify the probe flight reaches a real payment URL and extracts a real convenience fee.
- [x] Update `docs/architecture.md` and `docs/cleartrip-agent.md` with the current Cleartrip architecture and diagrams.
