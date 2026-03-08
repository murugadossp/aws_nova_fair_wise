# Cleartrip Agent — Improvements from 2026-03-07 23:20 Run

Summary of issues from the terminal log and changes made.

---

## 1. Session b389 (Flight 1 — IX-2935) FAILED: max_steps on fare summary

**What happened:** After extracting coupons, the **extract_fare_summary_booking** act ran with the "Apply coupon or gift card" dialog still open. The instruction did **not** tell the agent to dismiss the dialog first. The agent tried: Apply, OK, Remove, x, scrolling the dialog/page, etc., and hit **max_steps 16** without returning. Workflow status: **FAILED**. Flight 1 got a fallback fare_breakdown (base=7440, taxes=0, conv=0) and no payment URL.

**Root cause:** `extract_fare_summary_booking.md` had no “dismiss coupon dialog first” step. The agent was given only “You are on the booking page, fare summary on the right, scroll and extract.”

**Fix applied:**
- In **`instructions/extract_fare_summary_booking.md`**: Added a **First** step: if the "Apply coupon or gift card" dialog is open, **click outside** to close it (no X/Close button); do NOT click Apply/OK inside the dialog. Then locate the fare summary and extract.
- In **`config.yaml`**: **extract_fare_summary_booking** `max_steps` increased from **16 → 22** to allow more steps when the dialog is open.

---

## 2. Session 5b0f (Flight 2 — 6E-886): Applied a coupon by mistake

**What happened:** Same fare-summary act; no “dismiss first” instruction. The agent clicked **Apply** (applying a coupon), then **OK** on “Congrats! You saved ₹350”, then tried Remove/scroll/close. It eventually closed the menu, scrolled up, and extracted fare (base=6144, taxes=1297, total=7441) in **~1m 29s**.

**Fix:** Same as above — explicit “click **outside** the dialog; do NOT click Apply or OK” so the agent does not apply a coupon while trying to close.

---

## 3. CTFKAXIS discount wrong: 547 instead of 5547

**What happened:** Both workers returned **CTFKAXIS discount = 547**. The real offer is “Flat **₹5547** off”; the agent dropped the second “5” and returned 547. That made **best_price_after_coupon** too high (e.g. 6893/6894 instead of ~1893).

**Root cause:** Coupon instruction did not stress “full number” (e.g. 5547 not 547).

**Fix applied:**
- In **`instructions/extract_coupons_from_booking_page.md`** and **`instructions/select_fare_extract_coupons.md`**: For “Flat ₹X off”, use the **full** number X (e.g. 5547 not 547; 892 not 89). Do not truncate digits.

---

## 4. Typo: BOFCC vs BOBCC

**What happened:** Session 5b0f returned one coupon code as **"BOFCC"** in the think step (later corrected to BOBCC in the return). Minor; instruction already says “code exactly as shown.”

**Recommendation:** No code change; keep “exact code as shown” and monitor. If it recurs, add an example: “e.g. BOBCC not BOFCC.”

---

## 5. Flight 1 worker never reached payment flow

**What happened:** Because session b389 failed on **extract_fare_summary_booking** (max_steps), it never ran skip add-ons → fill traveler → payment page. So flight 1 had no **convenience_fee** from payment page and no **payment** URL; flight 2 had conv_fee=0 on booking page.

**Fix:** With the fare-summary instruction and max_steps fix, flight 1’s worker should more often complete fare summary, then skip add-ons → fill traveler → payment fare, so convenience_fee and payment URL are captured and can be reused for flight 2.

---

## Summary of file changes

| File | Change |
|------|--------|
| `instructions/extract_fare_summary_booking.md` | Add “First: if coupon dialog open, click outside to close; do NOT click Apply/OK.” Then locate fare summary and extract. |
| `instructions/extract_coupons_from_booking_page.md` | Discount: use **full** number (e.g. 5547 not 547); do not truncate. |
| `instructions/select_fare_extract_coupons.md` | Same discount clarification. |
| `config.yaml` | `extract_fare_summary_booking` max_steps: 16 → 22. |

Re-run the test to confirm: (1) no FAILED on fare summary, (2) no “Apply”/“OK” on the coupon dialog, (3) CTFKAXIS discount = 5547, (4) flight 1 gets payment fare and convenience_fee when the full flow completes.
