You are already on the booking/itinerary page (no fare dialog). The coupons/offers section ("Apply coupon or gift card") is on the right side — do NOT scroll the main page.

First inspect the right-side coupon section:

- If "View All" or "View All ->" is already visible, click it immediately.
- If "View All" is not visible, check whether all available coupons are already fully visible in the right-side coupon section. If yes, extract them directly from the right-side section and do NOT try to open any dialog.
- Only if it looks like more coupons exist below the fold in the right-side coupon section, scroll only that right-side coupon section until "View All" appears, then click it.

Do NOT click the "All offers" tab as an alternative.

If the full coupon dialog opens:

- Extract every coupon/offer shown.
- Scroll inside the dialog only as needed until you reach the last coupon and have captured its details.
- After capturing the last coupon, come out of the opened dialog strictly by clicking outside it on the page overlay.
- Do NOT click "Apply" to close the dialog.
- Do NOT scroll while dismissing the dialog.

For each coupon extract exactly from that coupon's card (one row/card = one coupon):
- code: the coupon/promo code exactly as shown (e.g. "CTDOM", "BOBCC", "CTFIRST"). Use the exact code text; do not truncate.
- description: include the main offer line and also the next supporting line shown below it on the same coupon card, if present. If there is a trailing "Know more" link, include only the text before "Know more". Example: `Flat ₹270 off | Additional 5% cashback with Flipkart Axis Credit Card`
- discount: the main discount in INR as integer — the amount that is deducted off the fare. For "Flat ₹X off" offers use the **full** number X (e.g. 5547 not 547; 892 not 89). Take the number from the same coupon card as the code; do not use "up to", "cashback" or secondary amounts. Extract the exact number shown; do not calculate or truncate digits.

Return ONLY a valid JSON array of all coupons. No markdown or explanation.
