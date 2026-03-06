Extract flights from this Cleartrip search results page that match: {{criteria}}.

Treat the flight results section as a structured dataset of repeating flight cards.

Return a JSON array with fields:
airline, flight_number, departure, arrival, duration, stops, price, url.


--------------------------------------------------

FLIGHT CARD STRUCTURE

Each flight result appears as a repeating card in the main results container.

Each card typically contains:

- airline name
- flight number
- departure time
- arrival time
- duration
- stops
- price
- "View Details" or "Book" link

Each card represents ONE flight option.

All extracted fields must belong to the SAME card.

Never mix fields from different cards.


--------------------------------------------------

VISIBILITY RULE

If flight cards are already visible:

extract data immediately.

Do NOT scroll unnecessarily.

If flight cards are not yet visible:

scroll slightly until the results container appears.


--------------------------------------------------

INTERACTION RULES

This task is data extraction, not navigation.

Do NOT:

- click flight cards
- click "Book"
- click "View Details"
- open popups
- navigate away from the results page

Only read visible card data from the DOM.


--------------------------------------------------

URL EXTRACTION RULES

Each card contains a booking or "View Details" link.

Extract the URL by reading the link's href attribute.

Do NOT click the link.

Valid URLs must:

- be absolute
- start with {{base_url}}/
- open the specific flight details page
- contain route and flight information

Reject URLs that are:

- homepage links
- navigation links
- advertisements
- filter links
- shorter than ~30 characters

Never construct URLs manually.
Never guess URLs.

Only return URLs that appear directly in the DOM.


--------------------------------------------------

DATA CLEANING RULES

Departure and arrival:

Return in HH:MM format.

Examples:
07:20
09:45


Stops conversion:

Nonstop → 0
1 stop → 1
2 stops → 2


Price:

Prices appear like:

₹8,760

Remove currency symbols and commas.

Return integer:

8760


--------------------------------------------------

INTERACTION STRATEGY

Treat the results list as a dataset.

Start scanning flight cards from the TOP of the list.

For each card:

1. read departure time
2. check if it matches the criteria
3. if it matches, extract the card


If 3 or more matching flights are already visible:

extract immediately and return.

Do NOT continue scrolling.


If no matching flights are visible:

scroll down once and continue scanning. Do not assume the list is sorted by departure; morning flights (e.g. 07:00–10:00) often appear further down the page. Do not return an empty array after only checking the first visible portion — scroll down at least 2–3 times if needed to find matching flights.


--------------------------------------------------

EARLY STOP OPTIMIZATION

Do NOT assume the default list order is by departure time. The first visible flights may be any order (e.g. by price or recommendation). Flights in a morning window (07:00–10:00) often appear lower on the page — scroll down to find them; do not scroll up and conclude there are none.

If the page is clearly sorted by departure (e.g. user applied "sort by departure" and the column shows it):

Ignore flights earlier than the requested window. Collect flights within the window. When you see a flight later than the window, stop and return what you collected.

If the list is not sorted by departure:

Scan the visible cards; if no matches, scroll down and scan again. Repeat until you have 3+ matching flights or reach the end of the list. Do not return an empty array after only one scroll.


--------------------------------------------------

RESULT VALIDATION

Before returning results verify:

- airline exists
- flight_number exists
- departure is HH:MM
- arrival is HH:MM
- stops is integer
- price is integer
- url is absolute
- url length > 30 characters
- url starts with {{base_url}}/

All fields must belong to the same flight card.


--------------------------------------------------

OUTPUT FORMAT

Return ONLY a valid JSON array.

Do NOT include:

- markdown
- explanations
- comments
- extra text

Example:

[
  {
    "airline": "IndiGo",
    "flight_number": "6E-484",
    "departure": "07:20",
    "arrival": "08:40",
    "duration": "1h 20m",
    "stops": 0,
    "price": 8760,
    "url": "https://www.cleartrip.com/flights/6E-484-BLR-HYD-10-Mar-2026"
  }
]