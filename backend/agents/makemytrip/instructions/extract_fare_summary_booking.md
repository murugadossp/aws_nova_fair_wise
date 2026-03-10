This is a DATA EXTRACTION task.

You are on the MakeMyTrip booking / itinerary page for one selected flight.

Locate the fare summary for this booking page and extract:

- `base_fare`
- `taxes`
- `convenience_fee`
- `total_fare`
- `fare_type` if visible

Rules:
- Do NOT click payment options or continue deeper into checkout in this step.
- If a coupon or offer dialog is open and blocks the fare summary, dismiss it by clicking outside or using the page's close control, then continue extraction.
- Scroll only the fare-summary area or page only as needed to see the full booking fare summary.
- If convenience fee is not shown on this booking page, return `0`.
- Return ONLY a valid JSON object that matches the schema.
