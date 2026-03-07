This is a DATA EXTRACTION task. Do NOT click any buttons or links.

On the final payment/checkout page, locate the fare summary panel on the right side of the page.

Scroll the right-side panel if needed to see the complete fare breakdown.

Extract the following from the fare summary:

- base_fare: the base fare amount in INR as an integer (e.g. 5500)
- taxes: total taxes and surcharges in INR as an integer (e.g. 1232)
- convenience_fee: the convenience fee in INR as an integer (e.g. 300). If no convenience fee is shown, use 0.
- total_fare: the final total amount in INR as an integer (e.g. 7032)

Return ONLY a valid JSON object with these four fields. No markdown or explanation.
