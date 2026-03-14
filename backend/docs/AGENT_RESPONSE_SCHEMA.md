# Travel agent response schema (fetch_offers=True)

When the app calls a travel agent’s `search(..., fetch_offers=True)` (Ixigo, Cleartrip, etc.), the agent returns a **standard dict shape** so the app can consume one structure regardless of platform.

**Summary:** **`filtered`** = Phase 2 output (all filtered flights) + one added field per flight: **`offers`** (object for top N, `null` for the rest). No new list shape is introduced; we only add the `offers` field to the existing Phase 2 structure.

## Response shape

All agents that support `fetch_offers` should return:

```json
{
  "telemetry": { "search_url": "...", "timings_ms": { ... } },
  "flights": [ /* raw Phase 1 extraction */ ],
  "filtered": [ /* app-ready list: all options, top N with offers — use this */ ],
  "offers_analysis": [ /* detailed offer objects for top N only */ ]
}
```

## `filtered` — app-ready list (use this)

**`filtered`** is an array of **all** flights that passed filters (departure window, max stops, sort). Each element has:

- **Canonical flight fields** (same for every item):  
  `platform`, `airline`, `flight_number`, `departure`, `arrival`, `duration`, `stops`, `price`, `book_url`, `from_city`, `to_city`, `date`, `travel_class` (or `class`)

- **`offers`**:  
  - For the **first N** flights (e.g. top 2): an object with `booking_url` (or `itinerary_url`), `fare_details` (or `fare_breakdown`), `coupons`, `best_price_after_coupon`.  
  - For the **rest**: `null`.

Agents may use slightly different keys internally (e.g. Cleartrip `fare_breakdown`, Ixigo `fare_details`); when building `filtered[].offers`, normalize to the same shape so the app can treat all platforms alike.

## App usage

1. **List options**: Iterate `response["filtered"]` and show every flight (airline, times, `price`).
2. **Deep link / coupons**: If `flight["offers"]` is not null, show “Book” using `flight["offers"]["booking_url"]`, show coupons and `best_price_after_coupon`.
3. **No offer data**: If `flight["offers"]` is null, show list price only and optionally a generic “View on [platform]” link (e.g. search URL from `telemetry.search_url`).

## Other keys

- **`flights`**: Raw extraction list (before normalizer). Use for debugging or unfiltered data.
- **`offers_analysis`**: One object per top-N flight (same order as first N in `filtered`). Use if you need the full offer payload without merging into `filtered`.

## Who implements this

- **Ixigo**: Returns `filtered` (Phase 2 + offers). See `agents/ixigo/docs/RESPONSE_SCHEMA.md`.
- **Cleartrip**: Returns `filtered` (Phase 2 + offers) in the same shape.
- Other travel agents with `fetch_offers` should follow this schema.
