#!/usr/bin/env bash
# run_test.sh — FareWise test launcher (lives in backend/tests/ alongside all test files)
#
# Activates the .venv, loads .env, then delegates to the appropriate
# test file or the central run_all_tests.py runner.
#
# Usage (from backend/tests/ OR from backend/):
#   ./tests/run_test.sh                          → run all tests (run_all_tests.py)
#   ./tests/run_test.sh ixigo                    → Ixigo E2E: all 7 tests (~8-10 min)
#   ./tests/run_test.sh ixigo --phase1-only      → Ixigo Phase 1 only (~3-4 min, no booking funnel)
#   ./tests/run_test.sh ixigo --skip-orchestrator→ Ixigo E2E, skip the full orchestrator test
#   ./tests/run_test.sh nova                     → Nova model tests only (no browser)
#   ./tests/run_test.sh unit                     → Nova model tests only (alias for nova)
#   ./tests/run_test.sh --headed                 → any suite, show Nova Act browser windows
#   ./tests/run_test.sh help                     → print this usage message
#
# Environment overrides:
#   FAREWISE_HEADED=1 ./tests/run_test.sh ixigo  → same as --headed

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────

# This script lives in backend/tests/ — the backend root is one level up.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$BACKEND_DIR/.venv/bin/activate"
ENV_FILE="$BACKEND_DIR/.env"
TESTS_DIR="$SCRIPT_DIR"
LOG_DIR="$BACKEND_DIR/logs"

# ── Colors ────────────────────────────────────────────────────────────────────
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'   # reset

# ── Cleanup trap ──────────────────────────────────────────────────────────────
START_TIME=$(date +%s)

on_exit() {
  local exit_code=$?
  local end_time
  end_time=$(date +%s)
  local elapsed=$(( end_time - START_TIME ))
  local minutes=$(( elapsed / 60 ))
  local seconds=$(( elapsed % 60 ))
  echo ""
  echo -e "${DIM}──────────────────────────────────────────────${NC}"
  if [ "$exit_code" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All tests passed.${NC}  Elapsed: ${minutes}m ${seconds}s"
  else
    echo -e "${RED}${BOLD}Tests failed (exit $exit_code).${NC}  Elapsed: ${minutes}m ${seconds}s"
  fi
  echo -e "${DIM}──────────────────────────────────────────────${NC}"
  exit "$exit_code"
}

trap on_exit EXIT

# ── Usage / help ──────────────────────────────────────────────────────────────
usage() {
  echo ""
  echo -e "  ${BOLD}FareWise — Test Launcher${NC}"
  echo ""
  echo -e "  ${CYAN}Usage (from backend/ root):${NC}"
  echo -e "    ./tests/run_test.sh                          Run all tests"
  echo -e "    ./tests/run_test.sh ixigo                    Ixigo E2E suite — all 7 tests  (~8-10 min)"
  echo -e "    ./tests/run_test.sh ixigo --phase1-only      Phase 1 only (~3-4 min, no booking)"
  echo -e "    ./tests/run_test.sh ixigo --skip-orchestrator  Skip orchestrator test"
  echo -e "    ./tests/run_test.sh nova                     Nova model tests only (no browser, ~30s)"
  echo -e "    ./tests/run_test.sh unit                     Alias for nova"
  echo -e "    ./tests/run_test.sh --headed                 Run with FAREWISE_HEADED=1 (show browser)"
  echo -e "    ./tests/run_test.sh help                     Show this message"
  echo ""
  echo -e "  ${CYAN}Companion script (simpler, per-agent):${NC}"
  echo -e "    ./tests/run_agent.sh ixigo                   Ixigo Phase 1+2+3 (simple runner)"
  echo -e "    ./tests/run_agent.sh ixigo --phase1-only     Ixigo Phase 1 only"
  echo -e "    ./tests/run_agent.sh cleartrip               Cleartrip agent"
  echo ""
  echo -e "  ${CYAN}Environment flags:${NC}"
  echo -e "    FAREWISE_HEADED=1 ./tests/run_test.sh ixigo  Show browser windows"
  echo ""
  echo -e "  ${CYAN}Examples:${NC}"
  echo -e "    cd backend/"
  echo -e "    ./tests/run_test.sh ixigo --phase1-only      # quick smoke test"
  echo -e "    ./tests/run_test.sh ixigo --headed            # watch Nova Act in browser"
  echo -e "    ./tests/run_test.sh nova                     # validate Bedrock credentials only"
  echo -e "    ./tests/run_test.sh                          # full suite (CI / pre-push)"
  echo ""
  echo -e "  ${CYAN}Log output:${NC}  $LOG_DIR/"
  echo ""
}

# ── Pre-flight checks ─────────────────────────────────────────────────────────

check_venv() {
  if [ ! -f "$VENV" ]; then
    echo -e "${RED}${BOLD}Error:${NC} .venv not found at $VENV"
    echo -e "  Create:  ${YELLOW}python3.12 -m venv .venv${NC}"
    echo -e "  Install: ${YELLOW}.venv/bin/pip install -r requirements.txt${NC}"
    exit 1
  fi
}

check_env() {
  if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a
    source "$ENV_FILE"
    set +a
    echo -e "${DIM}Loaded .env from $ENV_FILE${NC}"
  else
    echo -e "${YELLOW}Warning:${NC} .env not found at $ENV_FILE"
    echo -e "  Tests that use AWS Bedrock or Nova Act will fail without credentials."
    echo -e "  Copy the example:  ${YELLOW}cp $BACKEND_DIR/.env.example $ENV_FILE${NC}"
    echo ""
  fi
}


# ── Banner ────────────────────────────────────────────────────────────────────

print_banner() {
  local suite="$1"
  local run_date
  run_date=$(date '+%Y-%m-%d %H:%M:%S')

  echo ""
  echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${CYAN}║           FareWise — Test Suite Runner                   ║${NC}"
  echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo -e "  Suite:        ${BOLD}$suite${NC}"
  echo -e "  Date:         $run_date"
  echo -e "  Route:        Chennai → Bengaluru  (primary)  |  Mumbai → Delhi  (secondary)"
  echo -e "  Travel date:  2026-03-22"
  echo -e "  Python:       $(python --version 2>&1)"
  echo -e "  Headed:       ${FAREWISE_HEADED:-0}  (1 = show browser)"
  echo -e "  Log dir:      $LOG_DIR/"
  echo ""
}

# ── Argument parsing ──────────────────────────────────────────────────────────

SUITE=""
PHASE1_ONLY=0
SKIP_ORCHESTRATOR=0
HEADED=0

for arg in "$@"; do
  case "$arg" in
    --headed) HEADED=1 ;;
  esac
done

if [ "${FAREWISE_HEADED:-0}" = "1" ] || [ "$HEADED" -eq 1 ]; then
  export FAREWISE_HEADED=1
fi

if [ $# -eq 0 ]; then
  SUITE="all"
else
  case "$1" in
    help|--help|-h)
      usage
      exit 0
      ;;
    ixigo)
      SUITE="ixigo"
      shift
      for arg in "$@"; do
        case "$arg" in
          --phase1-only)       PHASE1_ONLY=1 ;;
          --skip-orchestrator) SKIP_ORCHESTRATOR=1 ;;
          --headed)            : ;;
          *)
            echo -e "${RED}Unknown flag for ixigo suite: $arg${NC}"
            usage
            exit 1
            ;;
        esac
      done
      ;;
    nova|unit)
      SUITE="nova"
      ;;
    --headed)
      SUITE="all"
      ;;
    *)
      echo -e "${RED}Unknown suite: '$1'${NC}"
      usage
      exit 1
      ;;
  esac
fi

# ── Environment setup ─────────────────────────────────────────────────────────

check_venv
# shellcheck disable=SC1090
source "$VENV"
check_env
mkdir -p "$LOG_DIR"

# ── Suite dispatch ────────────────────────────────────────────────────────────

case "$SUITE" in

  ixigo)
    if [ "$PHASE1_ONLY" -eq 1 ]; then
      print_banner "Ixigo E2E — Phase 1 only (fast, ~3-4 min)"
      echo -e "  Skipping: Phase 3 offer extraction, orchestrator test"
      echo ""
      cd "$BACKEND_DIR"
      exec python tests/test_ixigo_e2e.py --phase1-only
    elif [ "$SKIP_ORCHESTRATOR" -eq 1 ]; then
      print_banner "Ixigo E2E — All phases, skip orchestrator (~5-6 min)"
      echo -e "  Skipping: test_full_orchestrator_pipeline"
      echo ""
      cd "$BACKEND_DIR"
      exec python tests/test_ixigo_e2e.py --skip-orchestrator
    else
      print_banner "Ixigo E2E — Full suite, all 7 tests (~8-10 min)"
      echo -e "  Tests: session_logging, phase1_extraction, phase1_normalization,"
      echo -e "         phase1_filters, phase3_offers, on_progress_callbacks, orchestrator"
      echo ""
      cd "$BACKEND_DIR"
      exec python tests/test_ixigo_e2e.py
    fi
    ;;

  nova)
    print_banner "Nova Model Tests (no browser, ~30-60s)"
    echo -e "  Tests: Nova Lite (identifier), Nova Pro (reasoner), Nova Multimodal (validator)"
    echo ""
    cd "$BACKEND_DIR"
    exec python tests/run_all_tests.py --nova-only
    ;;

  all)
    print_banner "Full Test Suite — all groups"
    echo -e "  Order: Nova models → Agent tests → Ixigo E2E (Phase 1 fast path)"
    echo -e "  Estimated time: 15-25 min"
    echo ""
    cd "$BACKEND_DIR"
    exec python tests/run_all_tests.py
    ;;

esac
