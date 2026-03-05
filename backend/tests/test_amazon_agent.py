"""
Test: Amazon India — Nova Act Agent
Launches a real Chromium browser via Nova Act, searches amazon.in, and returns listings.

Run: python3 tests/test_amazon_agent.py
NOTE: Requires NOVA_ACT_API_KEY in .env. Opens a real browser window (~60s).
To see the browser live, run with FAREWISE_HEADED=1.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import add_agent_test_file_handler, get_logger
from agents.amazon import AmazonAgent

log = get_logger(__name__)


def assert_ok(condition: bool, message: str):
    if not condition:
        log.error("ASSERTION FAILED: %s", message)
        raise AssertionError(message)


def test_amazon_search(query="Sony WH-1000XM5", max_results=3):
    log.info("=== test_amazon_search: query='%s' max_results=%d ===", query, max_results)

    agent = AmazonAgent()
    log.info("Starting Nova Act browser on amazon.in...")
    results = agent.search(query=query, max_results=max_results)

    log.info("Received %d results", len(results))
    for i, r in enumerate(results, 1):
        log.info("[%d] title='%s'", i, r.get("title", "N/A")[:70])
        log.info("     price=₹%s  rating=%s (%s reviews)  availability=%s",
                 r.get("price"), r.get("rating"), r.get("review_count"), r.get("availability"))
        log.info("     url=%s", r.get("url", "")[:80])

    assert_ok(len(results) > 0,
              "Amazon agent returned 0 results — check NOVA_ACT_API_KEY and Bedrock region")
    assert_ok(all(r.get("price") for r in results), "Some results missing price field")
    assert_ok(all(r.get("platform") == "amazon" for r in results), "platform field must be 'amazon'")

    log.info("test_amazon_search PASSED  (%d results)", len(results))
    return results


if __name__ == "__main__":
    log_path = add_agent_test_file_handler("amazon")
    log.info("Test logs also written to %s", log_path)
    results = test_amazon_search("Sony WH-1000XM5 headphones", max_results=3)
    log.info("Full results JSON:\n%s", json.dumps(results, indent=2))
    log.info("Amazon agent test DONE")
