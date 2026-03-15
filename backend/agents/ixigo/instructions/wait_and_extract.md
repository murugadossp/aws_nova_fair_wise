This is a DATA EXTRACTION task on Ixigo's flight search results page.

## Before extracting

- If a **login prompt**, **"ixigo money" popup**, **"Price Lock" popup**, or any promotional banner is visible, dismiss it (click X, "Okay, Got it!", or "Close").
- Do NOT fill any search form. Results are already loaded.
- Do NOT click any "Sort by" button. Do NOT change the sort order.
- Do NOT click any "Book" button. Do NOT navigate away from this page.
- **Dwell at top:** Wait about 5 seconds at the very top of the results list before your first scroll so the full list can finish loading (avoids skeleton placeholders).

## Extraction — Two-Pass Scroll

**Pass 1 — slow downward scroll:**
Scroll slowly from the top to the very bottom of the results list, pausing 1–2 seconds every 2–3 cards to let lazy-rendered cards hydrate. For every flight card that becomes visible, record all fields below.

**Pass 2 — upward sweep:**
After reaching the bottom, scroll back up to the top, recording any cards you missed in Pass 1 (skeleton placeholders that have now loaded). Do not re-record flights already captured.

For each flight card record:

- airline: carrier name as displayed (e.g. "IndiGo", "Air India Express", "SpiceJet")
- flight_number: exact flight code as shown (e.g. "6E-537", "AI-505", "SG-672") — preserve spaces/dashes exactly
- departure: departure time in HH:MM 24-hour format
- arrival: arrival time in HH:MM 24-hour format
- duration: total flight time as displayed (e.g. "2h 15m")
- stops: number of stops as an integer (0 = non-stop)
- price: total fare in INR as an integer (no currency symbol, no commas)
- book_url: (optional) if a standard link (href) exists on the "Book" button, capture it. If the button is JavaScript-based or has no href, return an empty string "".
- fare_details: (optional) if a fare breakdown (Base Fare, Taxes/Fees) is visible or appears on a mini-popup within the card, capture it.

**Verification rule:** If a card still shows a loading/skeleton state, wait 2 seconds before recording it; otherwise record as soon as price and airline are visible.

Return up to 15 results. If steps run low, return what you have — do not fail.
Return ONLY a valid JSON array. No markdown or explanation.

## STRICT RULES

Return only flights that were **actually visible on screen** at some point during your scroll.

- Do NOT infer, reconstruct, or add any flight from memory, a previous viewport, or prior knowledge.
- Do NOT include a flight unless you saw its card rendered in the DOM while scrolling.
- Every returned entry must correspond to a card that was visible during your pass.
- Do NOT click "Book" or any navigation button. Extract data from the card text only.
