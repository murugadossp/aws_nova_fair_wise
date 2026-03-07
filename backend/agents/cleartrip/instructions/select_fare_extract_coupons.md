## PHASE 1: SELECT FARE

A "Select your fare" dialog has appeared.
If a login prompt or popup appears first, dismiss it.
The VALUE fare option should already be selected (leftmost option).
Click the "Continue" button at the bottom right of the dialog.

## PHASE 2: EXTRACT COUPONS

On the booking page that appears, the coupons/offers section ("Apply coupon or gift card") is on the right side — do NOT scroll the main page.

Scroll only the right-side coupon panel downward so the "View All" or "View All ->" link at the bottom becomes visible.

Click only the "View All" or "View All ->" link to open the full coupon list dialog.
Do NOT click individual coupon cards or the "All offers" tab — only click "View All".

Once the full coupon dialog opens, extract every coupon/offer shown.

For each coupon extract:

- code: the coupon/promo code (e.g. "CTDOM", "CTFIRST")
- description: the full offer description text
- discount: the discount amount in INR as integer (e.g. 270)

Return ONLY a valid JSON array of all coupons. No markdown or explanation.
