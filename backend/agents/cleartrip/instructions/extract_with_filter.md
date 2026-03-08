## PHASE 1: APPLY TIME FILTERS

As soon as any flight cards appear on the results page, IMMEDIATELY scroll the LEFT sidebar downward to find the **TIMINGS** section. Do NOT wait for all results to load — scroll the left sidebar NOW.

Apply only the sections below that list checkboxes (same time slots: Early morning, Morning, Afternoon, Evening, Night). If a section says "—" or is empty, skip it.

Use the UI buckets exactly as provided below. Do NOT reinterpret them into an exact HH:MM range. If a selected bucket is broad, that is expected on Cleartrip.

{{departure_instruction}}
{{arrival_instruction}}

Do NOT click any other filters or checkboxes. Do NOT scroll the main results area until PHASE 2.

## PHASE 2: EXTRACT ALL FLIGHTS

Extract every flight card top-to-bottom:

1. Read all flight cards in the current viewport.
2. Scroll down once.
3. Read all flight cards after the scroll.
4. Repeat until the page footer is visible or no new cards appear.

For each card extract these fields (all from the SAME card):

- airline: full airline name (e.g. "IndiGo", "Air India Express")
- flight_number: airline code + number (e.g. "6E-484", "IX-2935")
- departure: departure time in HH:MM 24-hour format
- arrival: arrival time in HH:MM 24-hour format
- duration: flight duration (e.g. "1h 20m")
- stops: integer (0 for non-stop, 1 for 1 stop)
- price: integer price in INR (remove ₹ and commas — e.g. ₹8,760 → 8760)

**Strict extraction rules:**

- Return every flight card you actually saw during this filtered scroll-through, and only those cards.
- Do NOT add any flight from memory, a previous viewport state, prior search knowledge, or inference.
- Do NOT mention or return a card unless you saw that specific card on screen during this run.
- If you are unsure whether a card was visible, leave it out.
- Keep the list in the same top-to-bottom order that the cards were seen while scrolling.

Return ONLY a valid JSON array of all flights. No markdown or explanation.
