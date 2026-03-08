If a login prompt, cookie banner, or app download popup appears, dismiss it.

Extract {{criteria}} from this search results page.

## SCROLLING STRATEGY

1. Read and record every flight card visible in the current viewport.
2. Scroll down once to reveal more cards.
3. Read and record every flight card visible after the scroll.
4. Repeat steps 2–3 until:
   - The page footer is visible, OR
   - A scroll reveals zero new flight cards.

Do NOT scroll back up. Move top-to-bottom in a single pass.

## FIELDS TO EXTRACT

For each flight card, extract these fields (all from the SAME card):

- airline: full airline name (e.g. "IndiGo", "Air India Express")
- flight_number: airline code + number (e.g. "6E-484", "IX-2935")
- departure: departure time in HH:MM 24-hour format
- arrival: arrival time in HH:MM 24-hour format
- duration: flight duration (e.g. "1h 20m")
- stops: integer (0 for non-stop, 1 for 1 stop)
- price: integer price in INR (remove ₹ and commas — e.g. ₹8,760 → 8760)

Never mix fields from different cards.

## STRICT RULES

Return only flights that were **actually visible on screen** at some point during your top-to-bottom scroll.

- Do NOT infer, reconstruct, or add any flight from memory, a previous viewport state, or prior knowledge.
- Do NOT include a flight unless you can confirm you saw its card while scrolling the results.
- If you did not see a flight card during your scroll, do not include it.
- Every returned entry must correspond to a card that was rendered and visible in the DOM during your pass.

## OUTPUT

Return ONLY a valid JSON array with ALL flights on the page.
Do NOT include markdown, explanations, or extra text.
