This is a DATA EXTRACTION task on MakeMyTrip's flight search results page.

## Before extracting

- If a **login / sign-in popup** is visible, close it (look for ✕ or "Close" button).
- If a **promotional / notification banner** is visible, dismiss it.
- Do NOT fill any search form. Results are already loaded.

## Extraction

Scroll from top to bottom of the results list. For every flight card that becomes
visible during your scroll, record:

- airline: carrier name as displayed (e.g. "IndiGo", "Air India")
- flight_number: flight code (e.g. "6E-537", "AI-505")
- departure: departure time in HH:MM 24-hour format
- arrival: arrival time in HH:MM 24-hour format
- duration: total flight time as displayed (e.g. "2h 15m")
- stops: number of stops as an integer (0 = non-stop)
- price: total fare in INR as an integer (no ₹ symbol, no commas)

Return up to 7 results. If steps run low, return what you have — do not fail.
Return ONLY a valid JSON array sorted by price ascending. No markdown or explanation.

## STRICT RULES

Return only flights that were **actually visible on screen** at some point during your scroll.

- Do NOT infer, reconstruct, or add any flight from memory, a previous viewport, or prior knowledge.
- Do NOT include a flight unless you saw its card rendered in the DOM while scrolling.
- Every returned entry must correspond to a card that was visible during your pass.
