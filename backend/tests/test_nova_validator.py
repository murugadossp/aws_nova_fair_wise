"""
Test: Nova Multimodal Embeddings — Validator
Tests image embedding and cosine similarity scoring.

Run: python3 tests/test_nova_validator.py
NOTE: Downloads two product images at test time (requires internet).
"""

import asyncio
import base64
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import get_logger
from nova.validator import NovaValidator

log = get_logger(__name__)

TEST_IMAGES = {
    "sony_angle1": "https://m.media-amazon.com/images/I/71o8Q5XJS5L._SL1500_.jpg",
    "sony_angle2": "https://m.media-amazon.com/images/I/61ZHWR7rmJL._SL1500_.jpg",
    "unrelated":   "https://m.media-amazon.com/images/I/71UXp4OjGzL._SL1500_.jpg",
}


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


async def fetch_image_b64(url: str) -> str:
    log.debug("Downloading image: %s", url[:80])
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        log.debug("Downloaded %d bytes from %s", len(resp.content), url[:60])
        return base64.b64encode(resp.content).decode()


async def test_embedding_similarity():
    log.info("=== test_embedding_similarity: cosine similarity between same/different products ===")

    validator = NovaValidator()

    log.info("Downloading test images...")
    try:
        ref_b64   = await fetch_image_b64(TEST_IMAGES["sony_angle1"])
        same_b64  = await fetch_image_b64(TEST_IMAGES["sony_angle2"])
        other_b64 = await fetch_image_b64(TEST_IMAGES["unrelated"])
    except Exception as e:
        log.warning("SKIP — could not download test images: %s", e)
        return

    log.info("Setting reference image (Sony headphones angle 1)...")
    ok = await validator.set_reference_image(ref_b64)
    assert_ok(ok, "Failed to embed reference image")

    log.info("Embedding same product (angle 2)...")
    same_vec  = validator._embed_image(same_b64)
    sim_same  = validator._cosine_similarity(validator._user_image_vec, same_vec)
    log.info("Similarity same product:  %.4f  (threshold=%.2f)", sim_same, validator.SIMILARITY_THRESHOLD)

    log.info("Embedding unrelated product...")
    other_vec  = validator._embed_image(other_b64)
    sim_other  = validator._cosine_similarity(validator._user_image_vec, other_vec)
    log.info("Similarity unrelated:     %.4f  (threshold=%.2f)", sim_other, validator.SIMILARITY_THRESHOLD)

    assert_ok(sim_same > validator.SIMILARITY_THRESHOLD,
              f"Same product similarity too low: {sim_same:.4f} < {validator.SIMILARITY_THRESHOLD}")
    assert_ok(sim_same > sim_other,
              f"Same product should outscore unrelated: {sim_same:.4f} vs {sim_other:.4f}")

    log.info("test_embedding_similarity PASSED  same=%.3f > threshold=%.2f > unrelated=%.3f",
             sim_same, validator.SIMILARITY_THRESHOLD, sim_other)


async def test_validate_results_passthrough():
    log.info("=== test_validate_results_passthrough: no reference image → all results pass ===")

    validator = NovaValidator()  # no reference image set

    results = [
        {"platform": "amazon",   "title": "Product A", "price": 1000, "thumbnail_url": None},
        {"platform": "flipkart", "title": "Product B", "price": 1200, "thumbnail_url": None},
    ]

    log.info("Calling validate_results with %d items and no reference image", len(results))
    validated = await validator.validate_results(results)

    log.info("Validated %d results", len(validated))
    for r in validated:
        log.info("  platform=%s is_same_product=%s similarity_score=%s",
                 r["platform"], r.get("is_same_product"), r.get("similarity_score"))

    assert_ok(len(validated) == 2, "Lost results during validation")
    assert_ok(all(r.get("is_same_product") for r in validated),
              "Should default is_same_product=True when no reference image")

    log.info("test_validate_results_passthrough PASSED")


async def main():
    log.info("Starting Nova Multimodal Validator tests  model=%s", NovaValidator.NOVA_EMBED_MODEL_ID)
    await test_embedding_similarity()
    await test_validate_results_passthrough()
    log.info("All validator tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
