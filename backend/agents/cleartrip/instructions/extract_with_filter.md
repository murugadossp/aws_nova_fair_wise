## PHASE 1: APPLY TIME FILTERS

As soon as any flight cards appear on the results page, IMMEDIATELY scroll the LEFT sidebar downward to find the **TIMINGS** section. Do NOT wait for all results to load — scroll the left sidebar NOW.

Apply only the sections below that list checkboxes (same time slots: Early morning, Morning, Afternoon, Evening, Night). If a section says "—" or is empty, skip it.

- **Departure:** Under "Taking off from {{from_city}}" in the TIMINGS section, click these checkboxes: {{departure_checkboxes}}
- **Arrival:** Under "Landing in {{to_city}}" in the TIMINGS section, click these checkboxes: {{arrival_checkboxes}}

**If arrival checkboxes are "—":** Do NOT scroll the left sidebar again. Go straight to PHASE 2 (extract flight cards). Do not look for or interact with the "Landing in {{to_city}}" section.

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

**Strict:** You must scroll the main results (steps 1–4 above) to find all flight cards, then return every flight you saw during that scroll-through. Include only flights that were actually visible on screen at some point during your scroll of the filtered results — do not add any flight from memory, a different viewport state, or inference. If you did not see a flight card while scrolling the results, do not include it.

Return ONLY a valid JSON array of all flights. No markdown or explanation.
