## PHASE 1: APPLY TIME FILTER

In the TIMINGS section on the left sidebar, under "Taking off from {{from_city}}", click these checkboxes: {{checkboxes}}
Do NOT click any other filters or checkboxes.

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

Return ONLY a valid JSON array of all flights. No markdown or explanation.
