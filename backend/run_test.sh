#!/usr/bin/env bash
# run_test.sh — FareWise test launcher
#
# Activates the .venv, loads .env, then delegates to the appropriate
# test file or the central run_all_tests.py runner.
#
# Usage (from the backend/ directory):
#   ./run_test.sh                          → run all tests (run_all_tests.py)
#   ./run_test.sh ixigo                    → Ixigo E2E: all 7 tests (~8-10 min)
#   ./run_test.sh ixigo --phase1-only      → Ixigo Phase 1 only (~3-4 min, no booking funnel)
#   ./run_test.sh ixigo --skip-orchestrator→ Ixigo E2E, skip the full orchestrator test
#   ./run_test.sh nova                     → Nova model tests only (no browser)
#   ./run_test.sh unit                     → Nova model tests only (alias for nova)
#   ./run_test.sh --headed                 → any suite, show Nova Act browser windows
#   ./run_test.sh help                     → print this usage message
#
# Environment overrides:
#   FAREWISE_HEADED=1 ./run_test.sh ixigo  → same as --headed

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────

# Always resolve relative to this script's location — works regardless of
# the caller's working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv/bin/activate"
ENV_FILE="$SCRIPT_DIR/.env"
TESTS_DIR="$SCRIPT_DIR/tests"
LOG_DIR="$SCRIPT_DIR/logs"

# ── Colors ────────────────────────────────────────────────────────────────────
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'   # reset

# ── Cleanup trap ──────────────────────────────────────────────────────────────
# Records the exit code and prints elapsed time before exiting — even on
# Ctrl-C or errexit.
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
  echo -e "  ${CYAN}Usage:${NC}"
  echo -e "    ./run_test.sh                          Run all tests (nova + agents + ixigo e2e)"
  echo -e "    ./run_test.sh ixigo                    Ixigo E2E suite — all 7 tests  (~8-10 min)"
  echo -e "    ./run_test.sh ixigo --phase1-only      Fast Ixigo tests only (~3-4 min, no booking)"
  echo -e "    ./run_test.sh ixigo --skip-orchestrator  Ixigo E2E, skip orchestrator test"
  echo -e "    ./run_test.sh nova                     Nova model tests only (no browser, ~30s)"
  echo -e "    ./run_test.sh unit                     Alias for nova"
  echo -e "    ./run_test.sh --headed                 Run with FAREWISE_HEADED=1 (show browser)"
  echo -e "    ./run_test.sh help                     Show this message"
  echo ""
  echo -e "  ${CYAN}Environment flags:${NC}"
  echo -e "    FAREWISE_HEADED=1 ./run_test.sh ixigo  Show browser windows (same as --headed)"
  echo ""
  echo -e "  ${CYAN}Examples:${NC}"
  echo -e "    cd backend/"
  echo -e "    ./run_test.sh ixigo --phase1-only      # quick smoke test, no booking funnel"
  echo -e "    ./run_test.sh ixigo --headed            # watch Nova Act interact with ixigo.com"
  echo -e "    ./run_test.sh nova                     # validate Bedrock credentials only"
  echo -e "    ./run_test.sh                          # full suite (CI / pre-push)"
  echo ""
  echo -e "  ${CYAN}Docs:${NC}  backend/docs/TESTING.md"
  echo ""
}

# ── Pre-flight checks ─────────────────────────────────────────────────────────

check_venv() {
  if [ ! -f "$VENV" ]; then
    echo -e "${RED}${BOLD}Error:${NC} .venv not found at $VENV"
    echo ""
    echo -e "  Create the virtual environment first:"
    echo -e "    ${YELLOW}cd $SCRIPT_DIR${NC}"
    echo -e "    ${YELLOW}python3.11 -m venv .venv${NC}"
    echo -e "    ${YELLOW}source .venv/bin/activate${NC}"
    echo -e "    ${YELLOW}pip install -r requirements.txt${NC}"
    echo ""
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
    echo -e "  Copy the example:  ${YELLOW}cp $SCRIPT_DIR/.env.example $ENV_FILE${NC}"
    echo ""
  fi
}

check_python() {
  # After activating .venv, 'python' and 'python3' both refer to the venv interpreter.
  local pyver
  pyver=$(python --version 2>&1 | awk '{print $2}')
  local pymajor
  pymajor=$(echo "$pyver" | cut -d. -f1)
  local pyminor
  pyminor=$(echo "$pyver" | cut -d. -f2)
  echo -e "${DIM}Python: $pyver${NC}"
  if [ "$pymajor" -lt 3 ] || ( [ "$pymajor" -eq 3 ] && [ "$pyminor" -lt 11 ] ); then
    echo -e "${YELLOW}Warning:${NC} Python $pyver detected — FareWise requires Python 3.11+."
    echo -e "  Rebuild your venv:  ${YELLOW}python3.11 -m venv .venv${NC}"
  fi
}

# ── Banner ────────────────────────────────────────────────────────────────────

print_banner() {
  local suite="$1"
  local run_date
  run_date=$(date '+%Y-%m-%d %H:%M:%S')
  local route="Chennai → Bengaluru  (primary)  |  Mumbai → Delhi  (secondary)"

  echo ""
  echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${CYAN}║           FareWise — Test Suite Runner                   ║${NC}"
  echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo -e "  Suite:        ${BOLD}$suite${NC}"
  echo -e "  Date:         $run_date"
  echo -e "  Route:        $route"
  echo -e "  Travel date:  2026-03-22  (one week out)"
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

# First pass: scan all args for --headed before we do anything else
for arg in "$@"; do
  case "$arg" in
    --headed) HEADED=1 ;;
  esac
done

# Apply --headed / env override
if [ "${FAREWISE_HEADED:-0}" = "1" ] || [ "$HEADED" -eq 1 ]; then
  export FAREWISE_HEADED=1
fi

# Identify the suite from the first positional argument
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
      # Parse subsequent flags
      shift
      for arg in "$@"; do
        case "$arg" in
          --phase1-only)      PHASE1_ONLY=1 ;;
          --skip-orchestrator) SKIP_ORCHESTRATOR=1 ;;
          --headed)            : ;;  # already handled above
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
      # ./run_test.sh --headed → run all tests with browser visible
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
check_python
mkdir -p "$LOG_DIR"

# ── Suite dispatch ────────────────────────────────────────────────────────────

case "$SUITE" in

  # ── Ixigo E2E — one or more test phases ──────────────────────────────────
  ixigo)
    if [ "$PHASE1_ONLY" -eq 1 ]; then
      print_banner "Ixigo E2E — Phase 1 only (fast, ~3-4 min)"
      echo -e "  Skipping: Phase 3 offer extraction, orchestrator test"
      echo ""
      cd "$SCRIPT_DIR"
      exec python tests/test_ixigo_e2e.py --phase1-only
    elif [ "$SKIP_ORCHESTRATOR" -eq 1 ]; then
      print_banner "Ixigo E2E — All phases, skip orchestrator (~5-6 min)"
      echo -e "  Skipping: test_full_orchestrator_pipeline"
      echo ""
      cd "$SCRIPT_DIR"
      exec python tests/test_ixigo_e2e.py --skip-orchestrator
    else
      print_banner "Ixigo E2E — Full suite, all 7 tests (~8-10 min)"
      echo -e "  Tests: session_logging, phase1_extraction, phase1_normalization,"
      echo -e "         phase1_filters, phase3_offers, on_progress_callbacks, orchestrator"
      echo ""
      cd "$SCRIPT_DIR"
      exec python tests/test_ixigo_e2e.py
    fi
    ;;

  # ── Nova model tests only — no browser required ────────────────────────────
  nova)
    print_banner "Nova Model Tests (no browser, ~30-60s)"
    echo -e "  Tests: Nova Lite (identifier), Nova Pro (reasoner), Nova Multimodal (validator)"
    echo ""
    cd "$SCRIPT_DIR"
    exec python tests/run_all_tests.py --nova-only
    ;;

  # ── Full suite — all test groups ──────────────────────────────────────────
  all)
    print_banner "Full Test Suite — all groups"
    echo -e "  Order: Nova models → Agent tests → Ixigo E2E (Phase 1 fast path)"
    echo -e "  Estimated time: 15-25 min"
    echo ""
    cd "$SCRIPT_DIR"
    exec python tests/run_all_tests.py
    ;;

esac
