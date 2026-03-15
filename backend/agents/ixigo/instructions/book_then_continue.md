Use minimal steps: reach the fare / booking page for the selected flight and stop.

**PRIORITY 1:** If a **"Price Lock" popup**, **login prompt**, **"ixigo money" popup**, or any promotional banner is blocking the page, dismiss it first (click "Okay, Got it!", X, or "Close").

## Step 1 — Sort by Departure (Earlier First)

Once at least one flight card is visible on the results page:
- Look for a sort button labelled **"Departure"** with secondary text **"Earlier First"** (or similar).
- Click it once to sort all flights by departure time ascending.
- Wait 1 second for the list to re-render.

This makes finding {{airline}} flight {{flight_number}} (dep ~{{departure}}) fast — just scan from top.

> If the Departure sort button is not visible or clicking it has no effect, skip this step and proceed to Step 2.

## Step 2 — Find and click Book

Find the flight card for **{{airline}} flight {{flight_number}}** departing at approximately **{{departure}}**.
Click that card's `Book` button only. Do NOT click any other flight's Book button.

**Scroll guidance:**
- Scroll down slowly. If **2 consecutive scrolls produce no change**, stop — you have reached the bottom.
- If the target card is not found after one full downward pass: scroll back to top, reload the page (browser reload, not the search button), wait 4 seconds, then try once more from the top.
- If still not found after the reload pass, return immediately without clicking anything.

Do NOT open filter panels, type into search boxes, or change sort order again after Step 1.

## Step 3 — Verify and stop

As soon as the booking page opens (shows fare details, pricing breakdown, itinerary summary, or offers panel):
- Verify the flight number shown matches **{{flight_number}}** character-by-character (ignoring spaces, dashes, case).
- **STRICT matching:** "6E0081", "6E-0081", "6E 0081" all match "6E0081" — but "6E6081" or "6E0011" do NOT.
- If the digits do not match, press Back, find the correct card, and click its Book button.
- Once confirmed — STOP and return immediately.

## STRICT RULES

- Do NOT click `Continue`, `Book Now`, `Next`, `Proceed`, or any forward-navigation button.
- Do NOT scroll or extract anything on the booking page itself.
- Do NOT fill in any traveller details or contact information.
- If a "Log in" popup appears, close it and return immediately — do NOT attempt to log in.
