"""
Run all FareWise tests in sequence.
Nova model tests first (fast, no browser), then Nova Act agents (slow, open browser).

Usage:
  python3 tests/run_all_tests.py              # all tests
  python3 tests/run_all_tests.py --nova-only  # Nova models only (no browser)
  python3 tests/run_all_tests.py --agents-only # Nova Act agents only
  python3 tests/run_all_tests.py --ixigo-e2e  # Ixigo E2E tests only (Phase 1–4)
  python3 tests/run_all_tests.py --ixigo-e2e --phase1-only  # Ixigo Phase 1 only (fast)
  python3 tests/run_all_tests.py --headed     # any suite + show Nova Act browser windows
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

# Ixigo E2E tests: Phase 1 (extraction), Phase 2 (normalization), Phase 3 (offers/coupons),
# and the full TravelOrchestrator WebSocket pipeline. Slower than individual agent tests.
IXIGO_E2E_TESTS = [
    ("Ixigo E2E — Full Suite (P1+P2+P3+Orchestrator)", "test_ixigo_e2e.py"),
]

# Ixigo Phase 1 only (fast, no booking funnel, no orchestrator)
IXIGO_PHASE1_TESTS = [
    ("Ixigo E2E — Phase 1 Only (fast)", "test_ixigo_e2e.py", ["--phase1-only"]),
]


def run_test(label: str, filename: str, extra_args: list = None) -> bool:
    path = os.path.join(TESTS_DIR, filename)
    log.info("─── Running: %s (%s)", label, filename)

    cmd = [sys.executable, path] + (extra_args or [])
    start = time.time()
    result = subprocess.run(
        cmd,
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

    # --headed: set FAREWISE_HEADED=1 so all child processes (Nova Act) show the browser window.
    # This must be applied before any subprocess.run() calls so the env is inherited.
    if "--headed" in args:
        os.environ["FAREWISE_HEADED"] = "1"
        log.info("--headed flag set: FAREWISE_HEADED=1 (browser windows will be visible)")

    # Mode flags
    run_nova          = "--agents-only" not in args and "--ixigo-e2e" not in args
    run_agents        = "--nova-only"   not in args and "--ixigo-e2e" not in args
    run_ixigo_e2e     = "--ixigo-e2e"   in args or (
                            "--nova-only" not in args
                            and "--agents-only" not in args
                            and "--ixigo-e2e" not in args
                        )

    # When --ixigo-e2e flag is explicitly set, run those tests; otherwise include in full run
    ixigo_e2e_explicit = "--ixigo-e2e" in args
    ixigo_phase1_only  = "--phase1-only" in args

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

    if ixigo_e2e_explicit or (not run_nova and not run_agents):
        log.info("══════════  IXIGO END-TO-END TESTS  (opens browser, slow)  ══════════")
        log.info("Phase 1 (extraction): ~60-90s | Phase 3 (offers): ~120-180s | Orchestrator: ~300s")
        if ixigo_phase1_only:
            log.info("Running Phase 1 only (--phase1-only set)")
            for entry in IXIGO_PHASE1_TESTS:
                label, filename = entry[0], entry[1]
                extra = entry[2] if len(entry) > 2 else []
                ok = run_test(label, filename, extra)
                (passed if ok else failed).append(label)
        else:
            for entry in IXIGO_E2E_TESTS:
                label, filename = entry[0], entry[1]
                extra = entry[2] if len(entry) > 2 else []
                ok = run_test(label, filename, extra)
                (passed if ok else failed).append(label)
    elif not ixigo_e2e_explicit and (run_nova or run_agents):
        # Full run: also include ixigo e2e in --phase1-only mode to keep suite duration reasonable
        log.info("══════════  IXIGO E2E TESTS  (Phase 1 only, fast path in full suite)  ══════════")
        for entry in IXIGO_PHASE1_TESTS:
            label, filename = entry[0], entry[1]
            extra = entry[2] if len(entry) > 2 else []
            ok = run_test(label, filename, extra)
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
