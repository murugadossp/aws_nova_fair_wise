Use minimal steps: reach the fare / booking page for the selected flight and stop.

**PRIORITY 1:** Click any button containing "Okay" or "Close" as soon as it appears (within ~500ms) to clear the overlay. If a **"Price Lock" popup**, **login prompt**, **"ixigo money" popup**, or any promotional banner is blocking the page, dismiss it first (click "Okay, Got it!", X, or "Close").

Find the flight card for {{airline}} flight {{flight_number}} priced at approximately ₹{{price}}.
Click that card's `Book` button only.
Do NOT click any other flight's Book button.

**If the target flight is not visible after scrolling the full page once:**
1. Scroll back to the top of the page.
2. Reload the page (use the browser reload, not the search button) and wait 4 seconds.
3. Scroll from top to bottom once more to find the card.
4. If still not found, return immediately without clicking anything — do NOT keep scrolling or clicking.
Do NOT open "Filter Flights", do NOT type in any search box, and do NOT change sort order.

If a fare-selection dialog, fare list, or mini booking sheet opens:
- choose the already-selected default fare if one is preselected
- otherwise choose the cheapest visible fare

As soon as the page shows fare details, pricing breakdown, itinerary summary, or an offers/coupon panel — verify the booking page is for **{{airline}} {{flight_number}}** by checking the flight number shown in the itinerary header or flight badge.

**STRICT flight number matching:** The flight number on the page must match **{{flight_number}}** exactly (ignoring spaces, dashes, and case). For example: "6E0081", "6E-0081", and "6E 0081" all match "6E0081", but "6E6081" or "6E0011" do NOT match. Compare the digit sequence character-by-character.

If the digits do not match, press the browser Back button, find the correct card, and click its Book button.

Once you have confirmed the correct flight's booking page is open — STOP and return immediately.

## STRICT RULES

- Do NOT click `Continue`, `Book Now`, `Next`, `Proceed`, or any forward-navigation button.
- Do NOT scroll or extract anything on this page.
- Do NOT fill in any traveller details or contact information.
- If a "Log in" popup appears, close it and return immediately — do NOT attempt to log in.
- Do NOT open filter panels or type into search boxes to find the flight; only scroll and refresh once if needed.
