This is a DATA EXTRACTION task. Do NOT click any buttons or links.

You are on the final payment / checkout page for one MakeMyTrip booking.

Locate the payment-page fare summary and extract:

- `base_fare`
- `taxes`
- `convenience_fee`
- `total_fare`

Rules:
- If convenience fee is already visible, extract it immediately and stop.
- Never click billing details, counters, accordions, drawers, `Know more`, or expandable rows to reveal the fare summary.
- Scroll only the fare-summary area or page only as needed to see the full fare summary.
- Return ONLY a valid JSON object that matches the schema.
