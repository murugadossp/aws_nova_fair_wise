This is a DATA EXTRACTION task.

You are on the Ixigo fare / booking page for **{{airline}} flight {{flight_number}}**.

## Step 0 — Verify correct flight

Before extracting anything, confirm the booking page is for flight **{{flight_number}}** by checking the itinerary header, flight badge, or fare summary title.

**STRICT flight number matching:** Compare the digit sequence character-by-character (ignoring spaces, dashes, and case). For example: "6E0081", "6E-0081", and "6E 0081" all match "6E0081", but "6E6081" or "6E0011" do NOT match.

If the digits do not match, return this JSON immediately without extracting anything:
`{"error": "wrong_page", "fare_details": {}, "coupons": []}`

## Step 1 — Dismiss any popups

If a **login prompt**, **"Price Lock" popup**, **"ixigo money" popup**, or any promotional overlay is visible, close it (click X, "Okay, Got it!", or "Close") before proceeding.

## Step 2 — Extract fare summary

Look for the **"Fare Summary"** card on the page. It shows a breakdown for 1 Traveller. Record:
- `base_fare`: the "Base Fare" amount in INR as an integer
- `taxes`: the "Taxes & Fees" amount in INR as an integer
- `total`: the "Total Amount" in INR as an integer

Ignore "Instant Off" — we calculate discounts ourselves from coupon data.

## Step 3 — Open the full coupon list

Above the Fare Summary card there is a **"View All Offers >"** link. Click it to open the full offers list.

- If a full coupon dialog or expanded panel opens, scroll **inside that panel only** to reveal all coupons.
- Do NOT scroll the main page; scroll only within the offers panel/dialog.

## Step 4 — Extract every coupon

For each coupon visible in the expanded list, record:
- `code`: exact promo / coupon code text (e.g. "SALE", "IXIGOFLY", "MONEY")
- `description`: full visible description for that coupon
- `discount`: main INR discount as an integer (e.g. 500, 1200). If the discount is shown as a percentage or is unclear, use 0.

## STRICT RULES

- Do NOT click `Continue`, `Book Now`, `Next`, `Proceed`, or any forward-navigation button.
- Do NOT apply any coupon. Only read and extract the information.
- Do NOT fill in any traveller details or contact information.
- Do NOT navigate away from this page.
- If a "Log in" popup appears, close it immediately — do NOT attempt to log in.

Return ONLY a valid JSON object with two keys: `fare_details` and `coupons`. No markdown or explanation.
