This is a DATA EXTRACTION task on Ixigo's flight search results page.

## Before extracting

- If a **login prompt**, **"ixigo money" popup**, **"Price Lock" popup**, or any promotional banner is visible, dismiss it (click X, "Okay, Got it!", or "Close").
- Do NOT fill any search form. Results are already loaded.
- Do NOT click any "Sort by" button. Do NOT change the sort order.
- Do NOT click any "Book" button. Do NOT navigate away from this page.

## Extraction

Scroll from top to bottom of the results list. For every flight card that becomes
visible during your scroll, record:

- airline: carrier name as displayed (e.g. "IndiGo", "Air India")
- flight_number: flight code (e.g. "6E-537", "AI-505")
- departure: departure time in HH:MM 24-hour format
- arrival: arrival time in HH:MM 24-hour format
- duration: total flight time as displayed (e.g. "2h 15m")
- stops: number of stops as an integer (0 = non-stop)
- price: total fare in INR as an integer (no currency symbol, no commas)
- book_url: (optional) if a standard link (href) exists on the "Book" button, capture it. If the button is JavaScript-based or has no href, return an empty string "".

**Verification rule:** If a card still shows a loading/skeleton state, wait 1–2 seconds before recording it; otherwise record as soon as details (price and airline) are visible.

Return up to 7 results. If steps run low, return what you have — do not fail.
Return ONLY a valid JSON array. No markdown or explanation.

## STRICT RULES

Return only flights that were **actually visible on screen** at some point during your scroll.

- Do NOT infer, reconstruct, or add any flight from memory, a previous viewport, or prior knowledge.
- Do NOT include a flight unless you saw its card rendered in the DOM while scrolling.
- Every returned entry must correspond to a card that was visible during your pass.
- Do NOT click "Book" or any navigation button. Extract data from the card text only.
