You are already on the booking/itinerary page (no fare dialog). The coupons/offers section ("Apply coupon or gift card") is on the right side — do NOT scroll the main page.

If "View All" or "View All ->" is already visible in the right panel, click it immediately. Otherwise scroll only the right-side coupon panel downward until that link is visible, then click it.

Do NOT click the "All offers" tab or individual coupon cards — only click "View All" or "View All ->" to open the full list dialog. If "View All" is not visible, scroll only the right-side coupon panel until that link appears; do not use the "All offers" tab as an alternative.

Once the full coupon dialog opens, extract every coupon/offer shown. Scroll inside the dialog only if more coupons are below the fold; if all are visible, extract immediately.

For each coupon extract exactly from that coupon's card (one row/card = one coupon):
- code: the coupon/promo code exactly as shown (e.g. "CTDOM", "BOBCC", "CTFIRST"). Use the exact code text; do not truncate.
- description: the full offer description text for that coupon
- discount: the main discount in INR as integer — the amount that is deducted off the fare. For "Flat ₹X off" offers use the **full** number X (e.g. 5547 not 547; 892 not 89). Take the number from the same coupon card as the code; do not use "up to", "cashback" or secondary amounts. Extract the exact number shown; do not calculate or truncate digits.

Return ONLY a valid JSON array of all coupons. No markdown or explanation.
