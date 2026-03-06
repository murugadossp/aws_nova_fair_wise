# CLEARTRIP FLIGHT RESULTS PAGE

Treat the flight results section as a **structured dataset of repeating flight cards**.

Flight search results appear as a vertical list of repeating flight cards in the **main results container in the center of the page**, below the search filters.

Focus only on the **flight results container** when extracting data.
Ignore navigation menus, headers, advertisements, promotional banners, sidebars, and footers.

Each **flight card represents a single flight option**.

## FLIGHT CARD STRUCTURE

Each flight card typically contains:

* airline name
* flight number
* departure time
* arrival time
* duration
* stops
* price
* "View Details" or "Book" link

### CARD EXTRACTION RULE

All extracted fields **must belong to the SAME flight card**.

Extraction process:

1. Identify a single flight card container.
2. Extract all fields from that container.
3. Move to the next card.

Never mix fields from different cards.

## VISIBILITY RULE

If flight cards are already visible on the page, **extract data immediately**.

Scroll **only if additional flight cards must load**.

Avoid repeated scrolling.

## BOOKING LINKS

Each card contains a **"View Details" or "Book" link**.

Extract the booking URL by reading the **href attribute directly from the DOM**.

Do **NOT click the link** to obtain the URL.

Clicking may open popups or modals and is unnecessary.

### VALID BOOKING URL RULES

A valid booking URL:

* starts with `https://www.cleartrip.com/`
* corresponds to the specific flight card
* contains route or flight information
* is longer than ~30 characters

### INVALID LINKS

Reject links that are:

* homepage links
* navigation links
* filter links
* promotional links
* javascript links
* URLs shorter than ~30 characters

## DATA FORMAT

### TIME

Departure and arrival times appear as:

HH:MM

Example:

07:20

### STOPS

Stops appear as:

Nonstop
1 stop
2 stops

Convert to integers:

Nonstop → 0
1 stop → 1
2 stops → 2

### PRICE

Prices appear in INR with currency symbol and commas.

Example:

₹8,760

Return price as an integer:

8760
