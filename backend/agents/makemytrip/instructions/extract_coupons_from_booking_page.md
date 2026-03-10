This is a DATA EXTRACTION task.

You are already on the MakeMyTrip booking / itinerary page for one selected flight.

Look for the coupon / promo / offers area on the booking page and extract every visible offer for this selected flight.

Rules:
- Do NOT click unrelated tabs or navigate away from the selected booking flow.
- If there is a `View All`, `See all offers`, `More offers`, or equivalent button for coupons, click it to open the full list.
- If a full coupon dialog opens, scroll inside that dialog only as needed to capture all coupons.
- After extracting all coupons, close the coupon dialog if it is open.
- Never apply a coupon in this step.

For each coupon return:
- `code`: exact promo / coupon code text
- `description`: full visible description for that coupon
- `discount`: main INR discount as an integer

Return ONLY a valid JSON array. No markdown or explanation.
