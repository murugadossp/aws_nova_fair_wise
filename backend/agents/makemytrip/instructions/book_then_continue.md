Use minimal steps to reach the booking review page for the selected flight.

## Step 1 — Find and click the flight card

Find the flight card for {{airline}} flight {{flight_number}} priced at ₹{{price}}.
Click that flight card's "View Prices" or "Book" button. Do NOT click any other flight.

## Step 2 — Wait for fare options to load

After clicking, a popup will appear. It may first show a loading message like
"Getting More Fares..." — this is normal and takes 10–30 seconds to resolve.

Do this:
1. Use wait("15") to wait 15 seconds.
2. Check if the popup now shows "BOOK NOW" buttons with fare columns (CLASSIC, VALUE, etc.).
3. If BOOK NOW buttons are NOT yet visible, use wait("15") one more time, then check again.
4. Do NOT close the popup. Do NOT click anything while waiting.

## Step 3 — Click the first BOOK NOW button

Once the fare options popup is visible (with BOOK NOW buttons):
- Click the FIRST "BOOK NOW" button — the leftmost one (CLASSIC / cheapest fare).
- Do NOT scroll the popup horizontally. Do NOT click VALUE or FARE BY MAKEMYTRIP.

## Step 4 — Return once on the booking page

As soon as the page shows a booking review, itinerary summary, traveller details, or fare
summary for this flight, stop and return immediately. Do NOT scroll or extract anything.
