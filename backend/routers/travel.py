"""Travel router — REST fallback + route parsing."""

import os
import sys
from fastapi import APIRouter
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

log = get_logger(__name__)
router = APIRouter()


class TravelRouteRequest(BaseModel):
    from_city:    str
    to_city:      str
    date:         str          # YYYY-MM-DD
    travel_class: str = "economy"
    cards:        list[str] = []


class VoiceParseRequest(BaseModel):
    transcript: str            # Raw speech-to-text output


@router.post("/parse-voice")
async def parse_voice_route(body: VoiceParseRequest):
    """
    Parse a natural language route string into structured form.
    e.g. "Mumbai to Delhi this Friday economy" →
         { from: "Mumbai", to: "Delhi", date: "2026-03-06", class: "economy" }

    This is a lightweight fallback — the sidepanel JS does this client-side
    for speed; the backend version is more accurate using Nova Lite.
    """
    import json, re, os
    from datetime import date, timedelta
    import boto3

    log.info("parse_voice_route: transcript='%s'", body.transcript[:80])
    transcript = body.transcript.lower()

    # Quick regex parse for common patterns
    cities = re.findall(
        r'\b(mumbai|delhi|bangalore|bengaluru|hyderabad|chennai|kolkata|pune|'
        r'ahmedabad|goa|jaipur|kochi|cochin|lucknow|chandigarh|indore)\b',
        transcript
    )

    travel_class = "economy"
    if "business" in transcript:
        travel_class = "business"
    elif "first" in transcript:
        travel_class = "first"

    # Relative date parsing
    today = date.today()
    parsed_date = today + timedelta(days=1)  # default: tomorrow

    if "today" in transcript:
        parsed_date = today
    elif "tomorrow" in transcript:
        parsed_date = today + timedelta(days=1)
    else:
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for i, day in enumerate(days):
            if day in transcript:
                current_dow = today.weekday()
                target_dow  = i
                delta = (target_dow - current_dow) % 7 or 7
                parsed_date = today + timedelta(days=delta)
                break

    result = {
        "from_city":    cities[0].title() if len(cities) > 0 else "",
        "to_city":      cities[1].title() if len(cities) > 1 else "",
        "date":         parsed_date.strftime("%Y-%m-%d"),
        "travel_class": travel_class,
        "confidence":   0.85 if len(cities) >= 2 else 0.3,
    }
    log.info("parse_voice_route result: %s→%s date=%s confidence=%.2f",
             result["from_city"], result["to_city"], result["date"], result["confidence"])
    return result
