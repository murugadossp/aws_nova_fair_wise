---
name: analyze-session
description: Analyze a completed FareWise session's logs and produce a phase-by-phase diagnostic report with issues and recommendations. Use when the user asks to analyze a session, review logs, or after a session completes.
tools: Read, Glob, Bash
---

# FareWise Session Analyzer

Read all files from the latest (or specified) session directory and produce a structured diagnostic report covering every pipeline phase, data quality scores, issues, and recommendations.

**Run once after a session completes. Do not save the report to a file unless the user asks.**

## Step 1: Locate the session directory

If a session_id was provided as an argument, find it:
```bash
find backend/logs backend/backend/logs -type d -name "<session_id>" 2>/dev/null | head -1
```

Otherwise find the most recent session:
```bash
find backend/logs backend/backend/logs -name "metadata.json" 2>/dev/null | xargs ls -t 2>/dev/null | head -1
```
Then use that file's parent directory as the session dir.

## Step 2: Read all session files

Read each file that exists in the session directory:
- `metadata.json` — route, agents, timestamps, status
- `nova_act_session.log` — all Python log output (agents, Nova Act, normalizer, reasoner)
- `execution.json` — per-phase timing and status entries
- `errors.json` — logged errors
- `screenshots_meta.json` — screenshot inventory (if any)

## Step 3: Parse the log by phase

Identify lines belonging to each phase by logger name / keywords:

| Phase | Log markers |
|-------|-------------|
| Phase 1 Extraction | `agents.ixigo.agent`, `agents.cleartrip.agent`, `agents.makemytrip.agent`, `nova_act.types.workflow __enter__`/`__exit__`, `Phase 1:` |
| Phase 2 Normalization | `nova.flight_normalizer`, `FlightNormalizer:` |
| Phase 3 Offer Extraction | `_process_one_target`, `_run_offer_loop`, `booking page →`, `coupons extracted`, `fare base=`, `offer_extracted` |
| Phase 4 Nova Pro Reasoning | `nova.reasoner`, `NovaReasoner Phase 4` |
| Orchestrator | `agents.orchestrator` |

## Step 4: Output the report

```
═══════════════════════════════════════════════
FAREWISE SESSION ANALYSIS
Session : <session_id>   Status: ✅ completed / ❌ failed / ⚠️ in_progress
Route   : <from> → <to>  |  <travel_date>  |  <class>
Agents  : <list>
Duration: <timestamp_start> → <timestamp_end>  (<Xs total>)
═══════════════════════════════════════════════

── PHASE 1: Extraction ─────────────────────────
Status  : ✅ / ⚠️ / ❌
Workflows started : N
Flights extracted : N  (per agent if multiple)
Duration : Xs
Key events:
  • <notable lines — workflow IDs, flight counts, wait_for_results outcomes>
Issues:
  • <timeout warnings, fallback to static sleep, unexpectedly low flight counts>

── PHASE 2: Normalization ──────────────────────
Status  : ✅ / ⚠️ / ❌
Input → Output : N → N flights
Filters applied : <list>
Deduplication  : N removed
Duration : Xs
Issues:
  • <anything unusual — all dropped, filter too aggressive>

── PHASE 3: Offer Extraction ───────────────────
Status  : ✅ / ⚠️ / ❌
Targets : N flights  |  Parallel sessions: N
Completed : N/N  |  Failed: N/N
Per-flight:
  [N/N] <airline> <fno>  ✅  base=₹X  taxes=₹Y  conv=₹Z  coupons=N
  [N/N] <airline> <fno>  ⚠️  <failure reason>
Duration : Xs
Issues:
  • <wait_for_selector timeouts, booking page failures, 0 coupons>

── PHASE 4: Nova Pro Reasoning ─────────────────
Status  : ✅ / ⚠️ / ❌
Flights sent   : N
Winner         : <airline> <fno>  dep=HH:MM  ₹raw → ₹effective  card=<card>
Reasoning      : "<reasoning_user>"
All results ranked:
  1. <fno>  raw=₹X  effective=₹Y  saving=₹Z  card=<card>
  2. ...
Duration : Xs  (includes Bedrock API call)
Issues:
  • <JSON parse failures, fallback triggered, truncated all_results>

── ORCHESTRATOR ────────────────────────────────
Coupon scope : N flights  [list IDs]
Session      : finalized as <status>

═══════════════════════════════════════════════
ISSUES SUMMARY
═══════════════════════════════════════════════
🔴 Critical  — <issue>
🟡 Warning   — <issue>
🔵 Info      — <issue>

═══════════════════════════════════════════════
RECOMMENDATIONS
═══════════════════════════════════════════════
1. <Actionable recommendation based on each issue found>
   Examples:
   - wait_for_selector timeouts → "Increase selector timeout from 1000ms in _wait_for_results"
   - 0 coupons on all flights   → "Verify booking page URL format hasn't changed"
   - Nova Pro fallback triggered → "Check Bedrock credentials / quota in us-east-1"
   - session status not completed → "Check for unhandled exceptions in orchestrator"

═══════════════════════════════════════════════
DATA QUALITY SCORE
═══════════════════════════════════════════════
Phase 1 Extraction    : X/10
Phase 2 Normalization : X/10
Phase 3 Offers        : X/10
Phase 4 Reasoning     : X/10
Overall               : X/10
```

## Scoring rubric

| Phase | 10/10 | Deductions |
|-------|-------|-----------|
| Phase 1 | All workflows succeeded, ≥5 flights extracted | −2 per workflow failure, −1 per timeout warning |
| Phase 2 | Output ≥3 flights after filters | −3 if output <2, −1 per filter dropping >50% of input |
| Phase 3 | All targets completed with fare data | −2 per failed target, −1 per missing coupon data |
| Phase 4 | Nova Pro returned full `all_results` matching input count | −5 for fallback, −2 for truncated results, −1 for missing `reasoning_user` |
