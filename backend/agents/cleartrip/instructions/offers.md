For the flights currently shown on this Cleartrip search results page (the ones you just extracted), find what offers or discounts are available. Collect all offer details, apply each offer one by one, and note the price for each flight after applying the offer.
Return a JSON object with two fields: "offers_applied" (array of objects with flight_reference or airline+flight_number, offer_name, price_after_offer in INR), and "suggestion" (string recommending which offer to use and why).
After you have the data, return your JSON and then stop; do not continue clicking.
