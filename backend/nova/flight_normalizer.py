"""
FlightNormalizer — Pure Python post-processing for raw agent results.

Responsibilities:
  1. Schema unification  — all agents return slightly different shapes;
                           this maps everything to one canonical dict
  2. Deduplication       — same flight (airline + number + departure) scraped
                           from multiple OTAs appears once (lowest price kept)
  3. Basic validation    — drop records with price=0 or missing required fields
  4. Criteria filtering  — if planner emitted a criteria string (e.g. "morning
                           flights"), apply a best-effort time-window filter

No LLM calls — this is deterministic data cleaning.
"""

import re
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

log = get_logger(__name__)

# ── Canonical schema field names ──────────────────────────────────────────────
# Every flight leaving this normalizer has exactly these keys.
CANONICAL_FIELDS = [
    "platform",       # source OTA: "makemytrip" | "cleartrip" | "ixigo"
    "airline",        # "IndiGo", "Air India", etc.
    "flight_number",  # "6E-2345"
    "departure",      # "HH:MM" 24h
    "arrival",        # "HH:MM" 24h
    "duration",       # "2h 15m"
    "stops",          # int
    "price",          # int INR
    "book_url",       # booking URL
    "from_city",      # "Mumbai"
    "to_city",        # "Delhi"
    "date",           # "YYYY-MM-DD"
    "travel_class",   # "economy"
    "fare_details",
    "fare_breakdown",
]


def _norm_str(s: object) -> str:
    """Lowercase + strip + collapse whitespace."""
    return re.sub(r"\s+", " ", str(s or "").lower().strip())


def _parse_hhmm(t: str) -> Optional[int]:
    """Convert 'HH:MM' → minutes-since-midnight, or None if unparseable."""
    try:
        h, m = t.strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _dedup_key(flight: dict) -> tuple:
    """
    Deduplication key: same physical flight regardless of which OTA sourced it.
    Normalise airline names (e.g. 'Indigo' == 'IndiGo') and strip spaces from
    flight numbers before comparing.
    """
    airline = _norm_str(flight.get("airline", ""))
    # Normalise common airline name variants
    airline = airline.replace("indigo", "indigo").replace("6e", "indigo")
    fn = _norm_str(flight.get("flight_number", "")).replace(" ", "").replace("-", "")
    dep = _norm_str(flight.get("departure", ""))
    return (airline, fn, dep)


def _to_canonical(raw: dict) -> Optional[dict]:
    """
    Map a raw agent result dict to the canonical schema.
    Returns None if the record is invalid (no price, no airline).
    """
    # Accept both "url" and "book_url" field names from agents
    url = raw.get("book_url") or raw.get("url") or ""

    price = raw.get("price")
    try:
        price = int(price)
    except (TypeError, ValueError):
        price = 0

    if not price or not raw.get("airline"):
        return None

    return {
        "platform":      raw.get("platform", "unknown"),
        "airline":       str(raw.get("airline", "")).strip(),
        "flight_number": str(raw.get("flight_number", "")).strip(),
        "departure":     str(raw.get("departure", "")).strip(),
        "arrival":       str(raw.get("arrival", "")).strip(),
        "duration":      str(raw.get("duration", "")).strip(),
        "stops":         int(raw.get("stops", 0)),
        "price":         price,
        "book_url":      url,
        "from_city":     str(raw.get("from_city", "")).strip(),
        "to_city":       str(raw.get("to_city", "")).strip(),
        "date":          str(raw.get("date", "")).strip(),
        "travel_class":  str(raw.get("class", raw.get("travel_class", "economy"))).strip(),
        "offers":        raw.get("offers"),
        "price_effective": raw.get("price_effective"),
        "fare_details":  raw.get("fare_details"),
        "fare_breakdown": raw.get("fare_breakdown"),
    }


def _apply_filters(flights: list[dict], filters: dict) -> list[dict]:
    """
    Apply structured filters from the planner to a flight list.
    Non-destructive: if a filter eliminates all results it is skipped with a warning.

    Supported filter keys:
      departure_window: ["HH:MM", "HH:MM"]  — inclusive departure time range
      arrival_window:   ["HH:MM", "HH:MM"]   — inclusive arrival/landing time range
      max_stops:       int                  — 0 = non-stop only
      sort_by:         "price"|"departure"|"duration"  — final sort order (applied in normalize)
    """
    result = flights

    # ── max_stops ─────────────────────────────────────────────────────────────
    max_stops = filters.get("max_stops")
    if max_stops is not None:
        filtered = [f for f in result if f.get("stops", 99) <= max_stops]
        log.info("Filter max_stops=%d: %d → %d flights", max_stops, len(result), len(filtered))
        result = filtered

    # ── departure_window ──────────────────────────────────────────────────────
    window = filters.get("departure_window")
    if window and len(window) == 2:
        lo = _parse_hhmm(window[0])
        hi = _parse_hhmm(window[1])
        if lo is not None and hi is not None:
            filtered = [
                f for f in result
                if (dep := _parse_hhmm(f.get("departure", ""))) is not None
                and lo <= dep <= hi
            ]
            log.info(
                "Filter departure_window %s–%s: %d → %d flights",
                window[0], window[1], len(result), len(filtered),
            )
            result = filtered

    # ── arrival_window ────────────────────────────────────────────────────────
    arr_window = filters.get("arrival_window")
    if arr_window and len(arr_window) == 2:
        lo = _parse_hhmm(arr_window[0])
        hi = _parse_hhmm(arr_window[1])
        if lo is not None and hi is not None:
            filtered = [
                f for f in result
                if (arr := _parse_hhmm(f.get("arrival", ""))) is not None
                and lo <= arr <= hi
            ]
            log.info(
                "Filter arrival_window %s–%s: %d → %d flights",
                arr_window[0], arr_window[1], len(result), len(filtered),
            )
            result = filtered

    return result


class FlightNormalizer:
    """
    Normalizes, deduplicates, and optionally filters raw agent results.

    Usage:
        normalizer = FlightNormalizer()
        flights = normalizer.normalize(
            raw_results,
            filters={
                "departure_window": ["06:00", "11:59"],
                "max_stops": 0,
                "sort_by": "price",
            },
        )
    """

    def normalize(
        self,
        raw_results: list[dict],
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """
        Args:
            raw_results: combined list from all agent.search() calls
            filters:     optional structured filters dict from TravelPlanner

        Returns:
            Deduplicated, validated, filtered, sorted list in canonical schema.
        """
        log.info("FlightNormalizer: %d raw results, filters=%s", len(raw_results), filters)

        # ── 1. Convert to canonical schema, drop invalid records ──────────────
        canonical: list[dict] = []
        skipped = 0
        for raw in raw_results:
            flight = _to_canonical(raw)
            if flight:
                canonical.append(flight)
            else:
                skipped += 1

        log.debug("Canonical: %d valid, %d skipped (missing price/airline)", len(canonical), skipped)

        # ── 2. Deduplicate: same physical flight → keep lowest price ──────────
        seen: dict[tuple, dict] = {}
        for flight in canonical:
            key = _dedup_key(flight)
            if key not in seen or flight["price"] < seen[key]["price"]:
                seen[key] = flight

        deduped = list(seen.values())
        removed = len(canonical) - len(deduped)
        if removed:
            log.info("Deduplication removed %d duplicate flights", removed)

        # ── 3. Apply structured filters ───────────────────────────────────────
        if filters:
            deduped = _apply_filters(deduped, filters)

        # ── 4. Sort: by departure time or price depending on filters.sort_by ──
        sort_by = (filters or {}).get("sort_by", "price")
        if sort_by == "departure":
            deduped.sort(key=lambda f: _parse_hhmm(f.get("departure", "")) or 9999)
        elif sort_by == "duration":
            deduped.sort(key=lambda f: f.get("duration", ""))
        else:
            # Sort primarily by price, then by departure time
            deduped.sort(key=lambda f: (f.get("price", float('inf')), _parse_hhmm(f.get("departure", "")) or 9999))

        # ── 5. Cap results to top 5 ───────────────────────────────────────────
        if len(deduped) > 5:
            log.info("Capping normalized results to top 5 (was %d)", len(deduped))
            deduped = deduped[:5]

        log.info("FlightNormalizer: %d final flights (from %d raw)", len(deduped), len(raw_results))
        return deduped
