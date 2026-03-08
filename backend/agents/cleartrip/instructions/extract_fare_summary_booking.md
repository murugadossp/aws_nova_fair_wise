This is a DATA EXTRACTION task.

You are on the booking/itinerary page ("Review your itinerary"). The fare summary (Base Fare, Taxes, Total) is in the **top-right** of the page.

**If no dialog is open:** The fare summary panel is already visible in the top-right. Locate it and extract immediately — do not scroll the main page or open any coupon panel.

**If the "Apply coupon or gift card" dialog is open** and blocking the view: dismiss it first. This dialog has **no X or Close button**. **Click outside the dialog** on the dark overlay or main content behind it; it will close. Do NOT click "Apply", "OK", or any button inside the dialog. Once the right-side fare summary panel is visible, proceed to extract.

Locate the fare summary panel on the right side (same page, not the payment page). Scroll only the right-side panel if needed to see Base Fare, Taxes, Convenience fee, and Total.

Extract the following from the fare summary:

- base_fare: the base fare amount in INR as an integer (e.g. 5500)
- taxes: total taxes and surcharges in INR as an integer (e.g. 1232)
- convenience_fee: the convenience fee in INR as an integer if shown; otherwise use 0
- total_fare: the total amount in INR as an integer (e.g. 7032)

Return ONLY a valid JSON object with these four fields. No markdown or explanation.
