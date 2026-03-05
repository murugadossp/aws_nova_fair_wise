"""
Run all FareWise tests in sequence.
Nova model tests first (fast, no browser), then Nova Act agents (slow, open browser).

Usage:
  python3 tests/run_all_tests.py              # all tests
  python3 tests/run_all_tests.py --nova-only  # Nova models only (no browser)
  python3 tests/run_all_tests.py --agents-only # Nova Act agents only
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from logger import get_logger

log = get_logger(__name__)

TESTS_DIR   = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(TESTS_DIR)

NOVA_TESTS = [
    ("Nova Lite — Identifier",       "test_nova_identifier.py"),
    ("Nova Pro — Reasoner",          "test_nova_reasoner.py"),
    ("Nova Multimodal — Validator",  "test_nova_validator.py"),
]

AGENT_TESTS = [
    ("Amazon India Agent",    "test_amazon_agent.py"),
    ("Flipkart Agent",        "test_flipkart_agent.py"),
    ("MakeMyTrip Agent",      "test_makemytrip_agent.py"),
    ("Goibibo Agent",         "test_goibibo_agent.py"),
    ("Cleartrip Agent",       "test_cleartrip_agent.py"),
]


def run_test(label: str, filename: str) -> bool:
    path = os.path.join(TESTS_DIR, filename)
    log.info("─── Running: %s (%s)", label, filename)

    start = time.time()
    result = subprocess.run(
        [sys.executable, path],
        cwd=BACKEND_DIR,
        capture_output=False,  # let output stream to terminal in real time
    )
    elapsed = time.time() - start

    if result.returncode == 0:
        log.info("PASS ✓  %s  (%.1fs)", label, elapsed)
    else:
        log.error("FAIL ✗  %s  (%.1fs)  exit_code=%d", label, elapsed, result.returncode)

    return result.returncode == 0


def main():
    args = sys.argv[1:]
    run_nova   = "--agents-only" not in args
    run_agents = "--nova-only"   not in args

    passed = []
    failed = []

    if run_nova:
        log.info("══════════  NOVA MODEL TESTS  (no browser)  ══════════")
        for label, filename in NOVA_TESTS:
            ok = run_test(label, filename)
            (passed if ok else failed).append(label)

    if run_agents:
        log.info("══════════  NOVA ACT AGENT TESTS  (opens browser)  ══════════")
        log.info("Each test launches a real Chromium and scrapes a live site — expect 30–90s each")
        for label, filename in AGENT_TESTS:
            ok = run_test(label, filename)
            (passed if ok else failed).append(label)

    total = len(passed) + len(failed)
    log.info("══════════  RESULTS: %d/%d passed  ══════════", len(passed), total)
    for t in passed:
        log.info("  ✓  %s", t)
    for t in failed:
        log.error("  ✗  %s", t)

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
