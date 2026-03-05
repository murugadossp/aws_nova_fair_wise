#!/usr/bin/env bash
# run_agent.sh — Run FareWise agents / Nova model tests
# Usage: ./tests/run_agent.sh <agent|group> [-h|--help]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$BACKEND_DIR/.venv/bin/activate"
TESTS="$SCRIPT_DIR"

# ── Colors ──────────────────────────────────────────────────────────────────
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

# ── Help ─────────────────────────────────────────────────────────────────────
usage() {
  echo ""
  echo -e "  ${BOLD}FareWise — Agent Runner${NC}"
  echo ""
  echo -e "  ${CYAN}Usage:${NC}"
  echo -e "    ./tests/run_agent.sh <agent>          Run a single agent"
  echo -e "    ./tests/run_agent.sh <group>          Run a group of agents"
  echo -e "    ./tests/run_agent.sh -h | --help      Show this help"
  echo ""
  echo -e "  ${CYAN}Agents:${NC}"
  echo -e "    ${YELLOW}amazon${NC}       Amazon India product search          (Nova Act · browser)"
  echo -e "    ${YELLOW}flipkart${NC}     Flipkart product search              (Nova Act · browser)"
  echo -e "    ${YELLOW}mmt${NC}          MakeMyTrip flight search             (Nova Act · browser)"
  echo -e "    ${YELLOW}goibibo${NC}      Goibibo flight search                (Nova Act · browser)"
  echo -e "    ${YELLOW}cleartrip${NC}    Cleartrip flight search              (Nova Act · browser)"
  echo ""
  echo -e "  ${CYAN}Nova model tests:${NC}"
  echo -e "    ${YELLOW}identifier${NC}   Nova Lite  — product identification  (Bedrock · no browser)"
  echo -e "    ${YELLOW}validator${NC}    Nova Multimodal — image validator    (Bedrock · no browser)"
  echo -e "    ${YELLOW}reasoner${NC}     Nova Pro   — price reasoning         (Bedrock · no browser)"
  echo ""
  echo -e "  ${CYAN}Groups:${NC}"
  echo -e "    ${YELLOW}products${NC}     amazon + flipkart"
  echo -e "    ${YELLOW}travel${NC}       mmt + goibibo + cleartrip"
  echo -e "    ${YELLOW}nova${NC}         identifier + validator + reasoner"
  echo -e "    ${YELLOW}all${NC}          nova + products + travel  (slow — opens 5 browser windows)"
  echo ""
  echo -e "  ${CYAN}Examples:${NC}"
  echo -e "    ./tests/run_agent.sh amazon"
  echo -e "    ./tests/run_agent.sh travel"
  echo -e "    ./tests/run_agent.sh all"
  echo ""
}

# ── Activate venv ────────────────────────────────────────────────────────────
activate_venv() {
  if [ ! -f "$VENV" ]; then
    echo -e "${RED}Error: .venv not found.${NC}"
    echo -e "  Create:  ${YELLOW}uv venv .venv --python 3.11${NC}"
    echo -e "  Install: ${YELLOW}uv pip install -r requirements.txt${NC}"
    exit 1
  fi
  # shellcheck disable=SC1090
  source "$VENV"
  echo -e "${DIM}✓ venv activated${NC}"
}

# ── Run single test ───────────────────────────────────────────────────────────
_passed=0
_failed=0

run_test() {
  local label="$1"
  local script="$2"

  echo ""
  echo -e "${BOLD}${CYAN}── $label ──────────────────────${NC}"

  if python "$TESTS/$script"; then
    echo -e "${GREEN}${BOLD}✓ PASSED${NC}  $label"
    (( _passed++ )) || true
  else
    echo -e "${RED}${BOLD}✗ FAILED${NC}  $label"
    (( _failed++ )) || true
  fi
}

# ── Summary ───────────────────────────────────────────────────────────────────
print_summary() {
  local total=$(( _passed + _failed ))
  echo ""
  echo -e "${BOLD}━━━ Results: $_passed / $total passed ━━━${NC}"
  if [ "$_failed" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All tests passed ✓${NC}"
  else
    echo -e "${RED}${BOLD}$_failed test(s) failed ✗${NC}"
    exit 1
  fi
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
if [ $# -eq 0 ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

activate_venv

case "$1" in

  # ── Single agents ──────────────────────────────────────────────────────────
  amazon)
    run_test "Amazon India Agent"   "test_amazon_agent.py"
    ;;
  flipkart)
    run_test "Flipkart Agent"       "test_flipkart_agent.py"
    ;;
  mmt|makemytrip)
    run_test "MakeMyTrip Agent"     "test_makemytrip_agent.py"
    ;;
  goibibo)
    run_test "Goibibo Agent"        "test_goibibo_agent.py"
    ;;
  cleartrip)
    run_test "Cleartrip Agent"      "test_cleartrip_agent.py"
    ;;

  # ── Nova model tests ───────────────────────────────────────────────────────
  identifier)
    run_test "Nova Lite — Identifier"       "test_nova_identifier.py"
    ;;
  validator)
    run_test "Nova Multimodal — Validator"  "test_nova_validator.py"
    ;;
  reasoner)
    run_test "Nova Pro — Reasoner"          "test_nova_reasoner.py"
    ;;

  # ── Groups ─────────────────────────────────────────────────────────────────
  products)
    echo -e "\n${BOLD}Group: products (amazon + flipkart)${NC}"
    run_test "Amazon India Agent"   "test_amazon_agent.py"
    run_test "Flipkart Agent"       "test_flipkart_agent.py"
    print_summary
    ;;
  travel)
    echo -e "\n${BOLD}Group: travel (mmt + goibibo + cleartrip)${NC}"
    run_test "MakeMyTrip Agent"     "test_makemytrip_agent.py"
    run_test "Goibibo Agent"        "test_goibibo_agent.py"
    run_test "Cleartrip Agent"      "test_cleartrip_agent.py"
    print_summary
    ;;
  nova)
    echo -e "\n${BOLD}Group: nova models (identifier + validator + reasoner)${NC}"
    run_test "Nova Lite — Identifier"       "test_nova_identifier.py"
    run_test "Nova Multimodal — Validator"  "test_nova_validator.py"
    run_test "Nova Pro — Reasoner"          "test_nova_reasoner.py"
    print_summary
    ;;
  all)
    echo -e "\n${BOLD}All tests — Nova models first, then browser agents (expect 5–8 min total)${NC}"
    run_test "Nova Lite — Identifier"       "test_nova_identifier.py"
    run_test "Nova Multimodal — Validator"  "test_nova_validator.py"
    run_test "Nova Pro — Reasoner"          "test_nova_reasoner.py"
    run_test "Amazon India Agent"           "test_amazon_agent.py"
    run_test "Flipkart Agent"               "test_flipkart_agent.py"
    run_test "MakeMyTrip Agent"             "test_makemytrip_agent.py"
    run_test "Goibibo Agent"                "test_goibibo_agent.py"
    run_test "Cleartrip Agent"              "test_cleartrip_agent.py"
    print_summary
    ;;

  # ── Unknown ────────────────────────────────────────────────────────────────
  *)
    echo -e "${RED}Unknown agent: '$1'${NC}"
    usage
    exit 1
    ;;
esac
