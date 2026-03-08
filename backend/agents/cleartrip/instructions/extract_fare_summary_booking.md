This is a DATA EXTRACTION task.

You are on the booking/itinerary page (the page where "Apply coupon or gift card" and the coupon list appear).

**First (use minimal steps):** If the "Apply coupon or gift card" dialog is open and blocking the view, dismiss it: this dialog has **no X or Close button** (even after scrolling). **Click outside the dialog** (on the page area behind it, e.g. the main content or a dark overlay) and it will close. Do NOT click "Apply", "OK", or any button inside the dialog — only click outside. Do NOT look for an X or Close button. Once the right-side fare summary panel is visible, proceed to extract.

Locate the fare summary panel on the right side of the page (same page, not the payment page). Scroll the right-side panel if needed to see the complete fare breakdown.

Extract the following from the fare summary:

- base_fare: the base fare amount in INR as an integer (e.g. 5500)
- taxes: total taxes and surcharges in INR as an integer (e.g. 1232)
- convenience_fee: the convenience fee in INR as an integer if shown; otherwise use 0
- total_fare: the total amount in INR as an integer (e.g. 7032)

Return ONLY a valid JSON object with these four fields. No markdown or explanation.
