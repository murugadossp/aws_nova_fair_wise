You are analyzing a FareWise flight search session. Your job is to parse the raw execution logs and produce a structured diagnostic report that a developer can use to understand what happened, identify failures, and improve the system.

Think carefully before writing each section — use the actual log content, not placeholders.

---

## PHASE BOUNDARY RULES — READ THESE BEFORE ANALYZING ANY SECTION

The logs are chronological. Use timestamps to assign every log line to exactly one phase:

| Phase | Starts at | Ends at (exclusive) |
|-------|-----------|---------------------|
| Phase 1 | Session start (`create_session`) | First line matching `"Phase 1: N flights extracted"` (inclusive) |
| Phase 2 | First `FlightNormalizer:` log line | Last `FlightNormalizer:` log line (inclusive) |
| Phase 3 | First `"fetch_offers: parallel mode"` log line | `"NovaReasoner Phase 4:"` log line |
| Phase 4 | First `"NovaReasoner Phase 4:"` log line | Session end |

**Critical rules that prevent misattribution:**

1. **nova_act.types.workflow `__enter__` lines** — Count ONLY those that appear BEFORE Phase 1 ends (i.e., before `"Phase 1: N flights extracted"`) as Phase 1 workflow starts. All other `__enter__` lines belong to Phase 3. Do NOT sum all workflow starts across the full log for Phase 1.

2. **wait_for_selector timeouts** — Attribute each timeout to the phase it occurred in, based on its timestamp. Timeouts that appear AFTER `"Phase 1: N flights extracted"` are Phase 3 issues (booking page navigation), NOT Phase 1 issues.

3. **Offers [N/N] results** — Count ALL lines matching `"Offers [N/N]: fare base="` as completed targets. Each such line is a success. A target is failed ONLY when `"Offers [N/N]: failed for"` appears. Do NOT stop counting after the first two — read every `_process_one_target` log line.

4. **Per-flight flight identity** — The `[N/N]` index in offer log lines is the target sequence number, not a flight number. Cross-reference against the `offers_analysis_scope` flight list (in execution.json) to map index to airline/flight_number. Index [1/5] = first flight in scope list, [2/5] = second, etc.

---

SESSION METADATA:
{{metadata}}

EXECUTION TIMELINE:
{{execution}}

ERRORS:
{{errors}}

LOG LINES (last {{log_line_count}} lines):
{{log_lines}}

---

Produce EXACTLY this report format. Replace every [placeholder] with real data extracted from the logs above. Apply the phase boundary rules above before filling in each section. Do not skip any section.

═══════════════════════════════════════════════
FAREWISE SESSION ANALYSIS
Session : {{session_id}}   Status: {{status}}
Route   : {{from_city}} → {{to_city}}  |  {{travel_date}}  |  {{travel_class}}
Agents  : {{agents}}
Duration: [timestamp_start] → [timestamp_end]  ([X]s total)
═══════════════════════════════════════════════

── PHASE 1: Extraction ─────────────────────────
Status  : [✅ success / ⚠️ partial / ❌ failed]
Nova Act workflows started : [N — count nova_act.types.workflow __enter__ lines that appear BEFORE "Phase 1: N flights extracted". Phase 3 __enter__ lines must NOT be counted here.]
Flights extracted : [N per agent, from "Phase 1: N flights extracted" lines]
Duration : [Xs — from session start timestamp to "Phase 1: N flights extracted" timestamp]
Key events:
  • [list 2–4 notable lines: workflow IDs created in Phase 1, flight counts, wait_for_results outcomes]
Issues:
  • [Only include wait_for_selector timeouts and other issues whose timestamps fall BEFORE "Phase 1: N flights extracted". Write "None" if there are no Phase 1 issues.]

── PHASE 2: Normalization ──────────────────────
Status  : [✅ / ⚠️ / ❌]
Input → Output : [N → N flights — from "FlightNormalizer: N raw results" and "N final flights" lines]
Filters applied : [list filters from "Filter X" log lines, e.g. max_stops=0, departure_window]
Deduplication  : [N removed — from FlightNormalizer dedup log lines, or "N/A"]
Duration : [Xs — from first to last FlightNormalizer log line]
Issues:
  • [e.g. filter dropped all flights, output < 2, or "None"]

── PHASE 3: Offer Extraction ───────────────────
Status  : [✅ / ⚠️ / ❌]
Targets : [N flights — from "fetch_offers: N targets" log line]
Parallel sessions : [N — from "parallel mode, N sessions" log line]
Per-flight results:
  [List ALL N targets. For each, find "Offers [N/N]: fare base=" for success or "Offers [N/N]: failed for" for failure.
   Map the index to the flight from execution.json offers_analysis_scope list.
   Format: [N/N] [airline] [flight_no]  ✅  base=₹[X]  taxes=₹[Y]  conv=₹[Z]  coupons=[C]
       or: [N/N] [airline] [flight_no]  ⚠️  [error reason]
   Do not omit any index. If a "fare base=" line is missing for an index, mark it ⚠️ unknown.]
Duration : [Xs — from "fetch_offers: parallel mode" to last _process_one_target log line]
Issues:
  • [Phase 3 booking page timeouts, ActExceededMaxStepsError, 0 coupons extracted — attribute by timestamp. Or "None".]

── PHASE 4: Nova Pro Reasoning ─────────────────
Status  : [✅ / ⚠️ / ❌]
Flights sent to Nova Pro : [N — from "NovaReasoner Phase 4: calculating" log line]
Winner  : [airline] [flight_no]  dep=[HH:MM]  ₹[raw] → ₹[effective]  card=[card_name]
Reasoning : "[reasoning_user text from log]"
All results ranked:
  1. [flight_no]  raw=₹[X]  effective=₹[Y]  saving=₹[Z]  card=[card]
  2. ...
  (use "rank=" log lines from NovaReasoner output)
Duration : [Xs — Bedrock API call time]
Issues:
  • [e.g. JSON parse failure, fallback to min-price triggered, all_results count < input count, reasoning text missing — or "None"]

── ORCHESTRATOR ────────────────────────────────
Coupon analysis scope : [N flights]  [[list flight IDs from offers_analysis_scope in execution.json]]
Session finalized as  : [status]

═══════════════════════════════════════════════
ISSUES SUMMARY
═══════════════════════════════════════════════
[List every issue found. For each, include: phase where it occurred (based on timestamp), log line evidence, and severity. Use:]
🔴 Critical  — [issue that caused data loss or session failure]
🟡 Warning   — [issue that degraded quality but session completed]
🔵 Info      — [minor observation worth noting]
[Write "No issues found." if everything was clean]

═══════════════════════════════════════════════
RECOMMENDATIONS
═══════════════════════════════════════════════
[For each issue above, give one concrete actionable fix. Be specific: include file name, function name, config value, or line context.]
1. [Recommendation]
[Write "No recommendations — session ran cleanly." if no issues]

═══════════════════════════════════════════════
DATA QUALITY SCORE
═══════════════════════════════════════════════
Phase 1 Extraction    : [X]/10  [one-line justification — only deduct for Phase 1 issues]
Phase 2 Normalization : [X]/10  [one-line justification]
Phase 3 Offers        : [X]/10  [one-line justification — only deduct for Phase 3 issues]
Phase 4 Reasoning     : [X]/10  [one-line justification]
Overall               : [X]/10

Scoring guide (apply deductions from the base of 10, WITHIN EACH PHASE'S TIME WINDOW):
  Phase 1: −2 per workflow failure (workflow exited with error in Phase 1), −1 per timeout/fallback-to-sleep WARNING that occurred BEFORE Phase 1 ended
  Phase 2: −3 if output < 2 flights after filters, −1 per filter dropping > 50% of input
  Phase 3: −2 per failed target (ActExceededMaxStepsError or "failed for" line), −1 per flight with 0 coupons when booking page loaded successfully; timeouts that occurred AFTER Phase 1 ended belong here, NOT in Phase 1 score
  Phase 4: −5 if fallback to min-price triggered, −2 if all_results count < input count, −1 if reasoning text missing
