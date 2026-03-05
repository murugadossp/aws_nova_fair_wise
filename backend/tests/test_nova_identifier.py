"""
Test: Nova Lite — Product Identifier
Tests both text-input and (optionally) image-input identification.

Run: python3 tests/test_nova_identifier.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import get_logger
from nova.identifier import NovaIdentifier

log = get_logger(__name__)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


async def test_text_query():
    log.info("=== test_text_query: Nova Lite text normalisation ===")
    identifier = NovaIdentifier()

    test_cases = [
        "Sony WH-1000XM5",
        "Samsung Galaxy S25+ 256GB",
        "Apple MacBook Air M4",
        "boAt Airdopes 411",
    ]

    for query in test_cases:
        log.info("Querying Nova Lite: '%s'", query)
        result = await identifier.identify_from_text(query)
        log.info("Result: success=%s product_name='%s' search_query='%s' confidence=%.2f",
                 result.get("success"), result.get("product_name"),
                 result.get("search_query"), result.get("confidence", 0))

        assert_ok(result.get("success"), f"identify_from_text failed for query='{query}'")
        assert_ok(bool(result.get("product_name")), "Missing product_name")
        assert_ok(bool(result.get("search_query")), "Missing search_query")

    log.info("test_text_query PASSED (%d queries)", len(test_cases))


async def test_image_identification():
    log.info("=== test_image_identification: Nova Lite image recognition ===")
    import base64

    image_path = os.path.join(os.path.dirname(__file__), "sample_product.jpg")
    if not os.path.exists(image_path):
        log.warning("SKIP — place a product screenshot at: %s", image_path)
        return

    log.info("Loading test image: %s", image_path)
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    identifier = NovaIdentifier()
    result = await identifier.identify_from_image(image_b64)
    log.info("Image result: success=%s product_name='%s' confidence=%.2f",
             result.get("success"), result.get("product_name"), result.get("confidence", 0))

    assert_ok(result.get("success"), "Image identification failed")
    log.info("test_image_identification PASSED")


async def main():
    log.info("Starting Nova Lite Identifier tests  model=%s", NovaIdentifier.MODEL_ID)
    await test_text_query()
    await test_image_identification()
    log.info("All identifier tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
