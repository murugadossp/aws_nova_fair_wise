"""
Test: Nova Pro — Price Reasoner
Tests effective price calculation with bank card offers.

Run: python3 tests/test_nova_reasoner.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import get_logger
from nova.reasoner import NovaReasoner

log = get_logger(__name__)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


SAMPLE_PRODUCT_RESULTS = [
    {
        "platform": "amazon",
        "title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
        "price": 24990,
        "original_price": 29990,
        "discount_pct": 17,
        "url": "https://www.amazon.in/dp/B09XS7JWHH",
        "thumbnail_url": "https://m.media-amazon.com/images/I/71o8Q5XJS5L.jpg",
        "availability": "in_stock",
    },
    {
        "platform": "flipkart",
        "title": "Sony WH-1000XM5 (Black)",
        "price": 26490,
        "original_price": 29990,
        "discount_pct": 12,
        "url": "https://www.flipkart.com/sony-wh-1000xm5",
        "thumbnail_url": "https://rukminim2.flixcart.com/image/312/312/xif0q/headphone.jpg",
        "availability": "in_stock",
    },
]

SAMPLE_FLIGHT_RESULTS = [
    {
        "platform": "makemytrip",
        "airline": "IndiGo",
        "flight_number": "6E-204",
        "price": 5891,
        "departure": "07:20",
        "arrival": "09:55",
        "duration": "2h 35m",
        "stops": 0,
        "book_url": "https://www.makemytrip.com/flights",
    },
    {
        "platform": "goibibo",
        "airline": "IndiGo",
        "flight_number": "6E-204",
        "price": 4890,
        "departure": "07:20",
        "arrival": "09:55",
        "duration": "2h 35m",
        "stops": 0,
        "book_url": "https://www.goibibo.com/flights",
    },
    {
        "platform": "cleartrip",
        "airline": "Air India",
        "flight_number": "AI-657",
        "price": 5102,
        "departure": "08:00",
        "arrival": "10:45",
        "duration": "2h 45m",
        "stops": 0,
        "book_url": "https://www.cleartrip.com/flights",
    },
]

SELECTED_CARDS = ["hdfc-regalia", "sbi-simplyclick"]


async def test_product_reasoning():
    log.info("=== test_product_reasoning: Nova Pro product price calculation ===")
    log.info("Input: amazon=₹24,990  flipkart=₹26,490  cards=%s", SELECTED_CARDS)

    reasoner = NovaReasoner()
    result = await reasoner.calculate_best_deal(
        results=SAMPLE_PRODUCT_RESULTS,
        selected_cards=SELECTED_CARDS,
        product_name="Sony WH-1000XM5 Wireless Headphones",
    )

    log.info("Raw response: %s", json.dumps(result, indent=2))

    assert_ok(result.get("success"), "calculate_best_deal returned failure")
    assert_ok(bool(result.get("winner")), "No winner in response")

    winner = result["winner"]
    log.info("Winner: platform=%s price_effective=₹%s card='%s' saving=₹%s",
             winner.get("platform"), winner.get("price_effective"),
             winner.get("card_used"), winner.get("saving_vs_max"))
    log.info("Reasoning: %s", result.get("reasoning", "")[:120])
    log.info("test_product_reasoning PASSED")


async def test_flight_reasoning():
    log.info("=== test_flight_reasoning: Nova Pro flight fare calculation ===")
    log.info("Input: MMT=₹5,891  Goibibo=₹4,890  Cleartrip=₹5,102  cards=%s", SELECTED_CARDS)

    reasoner = NovaReasoner()
    result = await reasoner.calculate_best_flight(
        flights=SAMPLE_FLIGHT_RESULTS,
        selected_cards=SELECTED_CARDS,
    )

    log.info("Raw response: %s", json.dumps(result, indent=2))

    assert_ok(result.get("success"), "calculate_best_flight returned failure")
    assert_ok(bool(result.get("winner")), "No winner in response")

    winner = result["winner"]
    log.info("Winner: platform=%s price_effective=₹%s card='%s'",
             winner.get("platform"), winner.get("price_effective"), winner.get("card_used"))
    log.info("Reasoning: %s", result.get("reasoning", "")[:120])
    log.info("test_flight_reasoning PASSED")


async def main():
    log.info("Starting Nova Pro Reasoner tests  model=%s", NovaReasoner.MODEL_ID)
    await test_product_reasoning()
    await test_flight_reasoning()
    log.info("All reasoner tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
