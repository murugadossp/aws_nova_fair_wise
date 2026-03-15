# Admin Dashboard — Session Logging & Debugging

## Overview

The Admin Dashboard is a comprehensive debugging and monitoring system for flight searches. Every search creates a **session directory** containing complete logs, screenshots, execution timelines, and error reports.

```
🎯 Visit: http://localhost:7891/admin
```

---

## Architecture

### Session Directory Structure

For each search, a directory is created at:

```
logs/
└── 2026-03-15/                          (date directory)
    └── a1b2c3d4/                        (session ID)
        ├── metadata.json                (search parameters, status)
        ├── nova_act_ixigo.log          (Nova Act workflow logs)
        ├── nova_act_cleartrip.log      (Nova Act workflow logs)
        ├── execution.json              (phase execution timeline)
        ├── errors.json                 (errors encountered)
        ├── screenshots_meta.json       (screenshot metadata)
        └── screenshots/                (actual PNG images)
            ├── ixigo_phase1_12-34-56.png
            ├── ixigo_phase2_12-35-10.png
            └── cleartrip_phase1_12-36-45.png
```

### Session Lifecycle

```
User clicks Search
    ↓
Backend: create_session()
  └─ Generate session_id (UUID truncated)
  └─ Create directory: logs/<date>/<session_id>/
  └─ Write metadata.json (search params)
    ↓
Phase 1: Extract
  ├─ log_nova_act(workflow_id, agent, logs)
  ├─ log_phase("extract", agent, duration, status)
  └─ capture_screenshot(agent, "phase1", path)
    ↓
Phase 2: Normalize
  ├─ log_phase("normalize", agent, duration, status)
  └─ capture_screenshot(agent, "phase2", path)
    ↓
Phase 3: Offers
  ├─ log_phase("offers", agent, duration, status)
  ├─ log_error(error_msg, context, agent) [if error]
  └─ capture_screenshot(agent, "phase3", path)
    ↓
Phase 4: Ranking
  └─ log_phase("ranking", "nova-pro", duration, status)
    ↓
Completion
  └─ finalize_session(status="completed", summary={...})
     └─ Update metadata.json with end timestamp and summary
```

---

## Admin Dashboard Features

### 1. Session List

**Left Panel: All Sessions**
- Organized by date (newest first)
- Shows: session_id, from → to, search date
- Real-time filtering by:
  - Date (calendar picker)
  - Session ID (text search)
- Live count of matching sessions

### 2. Session Details

**Click any session to expand:**

#### Metadata Tab
- Search parameters (cities, date, class, filters)
- Start/end timestamps
- Duration
- Overall status (completed/failed/in_progress)

#### Logs Tab
- Complete Nova Act workflow logs
- Searchable, scrollable
- Color-coded:
  - 🔴 Error (red)
  - 🟢 Success (green)
  - 🟡 Warning (yellow)
  - 🔵 Info (blue)

#### Execution Tab
- Timeline of all phases
- For each phase:
  - Name (Extract, Normalize, Offers, Ranking)
  - Agent (ixigo, cleartrip, nova-pro)
  - Duration in milliseconds
  - Status (success/error)
  - Timestamp
- **Timeline visualization:**
  - Blue dot = success
  - Red dot = error
  - Vertical line shows phase duration

#### Screenshots Tab
- Thumbnail gallery of all captured screenshots
- Metadata for each:
  - Agent name
  - Phase (phase1, phase2, etc.)
  - Timestamp
  - Description
- Click thumbnail to view full size

#### Errors Tab
- All errors encountered during the search
- For each error:
  - Agent
  - Context (what was happening)
  - Error message
  - Timestamp

### 3. Summary Statistics

- Total sessions across all dates
- Breakdown by status
- Breakdown by agent
- Total recent errors

---

## Backend Integration

### Session Logger API

```python
from session_logger import get_session_logger

logger = get_session_logger()

# 1. Start a search
session_id = logger.create_session(
    from_city="Chennai",
    to_city="Bengaluru",
    date="2026-04-02",
    travel_class="economy",
    agents=["ixigo", "cleartrip"],
    filters={"max_stops": 0}
)

# 2. Log during execution
logger.log_nova_act(
    workflow_id="workflow-123",
    agent_name="ixigo",
    logs_content="[Workflow logs here]"
)

logger.log_phase(
    phase="extract",
    agent="ixigo",
    duration_ms=12345,
    status="success",
    details={"flights_found": 6}
)

logger.capture_screenshot(
    agent_name="ixigo",
    phase="phase1",
    screenshot_path="/tmp/screenshot.png",
    description="Search results loaded"
)

# 3. Log errors if they occur
logger.log_error(
    error="Timeout waiting for results",
    context="Waiting for pricing results",
    agent="cleartrip"
)

# 4. Finalize the search
logger.finalize_session(
    status="completed",
    summary={
        "flights_found": 15,
        "offers_extracted": 5,
        "winner": "IndiGo 6E6081 at ₹3917"
    }
)
```

---

## Using in Orchestrator

Example integration in `orchestrator.py`:

```python
from session_logger import get_session_logger

class TravelOrchestrator:
    def __init__(self):
        self.logger = get_session_logger()

    async def search(self, from_city, to_city, date, ...):
        # Create session at start
        session_id = self.logger.create_session(
            from_city, to_city, date, travel_class, agents, filters
        )

        try:
            # During Phase 1
            await self._send({"type": "progress", "message": "Extracting flights..."})
            results = await self._run_agents(...)

            self.logger.log_phase("extract", "ixigo", duration, "success",
                                 {"flights": len(results)})

            # During Phase 3
            self.logger.log_phase("offers", "ixigo", duration, "success")

            # Final
            self.logger.finalize_session("completed", {"winner": best_flight})

        except Exception as e:
            self.logger.log_error(str(e), "Search failed", "orchestrator")
            self.logger.finalize_session("failed")
            raise
```

---

## Real-World Debugging Example

### Scenario: "Flight #3 is missing offer data"

**Steps:**

1. **Open Admin Dashboard:** http://localhost:7891/admin

2. **Find the session:**
   - Filter by date you ran the search
   - Click the session

3. **Check Metadata:**
   - Verify search parameters match what you intended
   - Check "Agents" field

4. **Review Logs:**
   - Click "Logs" tab
   - Search for "6E6815" (flight number)
   - Find when it tried to extract offers
   - Look for ERROR messages

5. **Check Timeline:**
   - Click "Execution" tab
   - Find "offers" phase for the agent
   - If duration is very short (<1000ms), extraction likely failed
   - If status is "error", see the error details

6. **View Screenshots:**
   - Click "Screenshots" tab
   - Find screenshots from offer extraction phase
   - Look for blank screens or timeout messages

7. **Check Errors:**
   - Click "Errors" tab
   - Find entries with agent name
   - Error message will tell you exact issue

---

## API Endpoints

### List Sessions

```bash
GET /api/admin/sessions

Response:
[
  {
    "session_id": "a1b2c3d4",
    "date": "2026-03-15",
    "from_city": "Chennai",
    "to_city": "Bengaluru",
    "timestamp_start": "2026-03-15T12:34:56.789Z",
    "status": "completed"
  }
]
```

### Get Session Details

```bash
GET /api/admin/sessions/{session_id}

Response:
{
  "session_id": "a1b2c3d4",
  "metadata": { ... },
  "logs": [ "log line 1", "log line 2", ... ],
  "execution": [ { "phase": "extract", "duration_ms": 1234, ... } ],
  "screenshots": [ { "path": "/logs/...", "agent": "ixigo", ... } ],
  "errors": [ { "error": "...", "context": "...", ... } ]
}
```

### Summary Statistics

```bash
GET /api/admin/summary

Response:
{
  "total_sessions": 42,
  "total_by_status": { "completed": 38, "failed": 3, "in_progress": 1 },
  "total_by_agent": { "ixigo": 42, "cleartrip": 35, "makemytrip": 28 },
  "recent_errors": 5
}
```

---

## Storage Considerations

Each session typically contains:
- **Metadata:** ~1-2 KB (JSON)
- **Logs:** 10-50 KB (text)
- **Screenshots:** 500 KB - 2 MB (3-10 images at ~200-500 KB each)
- **Execution/Errors:** 1-5 KB (JSON)

**Total per session:** ~1-3 MB

**Disk space for 100 sessions:** ~100-300 MB

### Cleanup Strategy (Optional)

To save disk space, periodically archive old sessions:

```bash
# Archive sessions older than 7 days
tar -czf logs/archive-2026-03-08.tar.gz logs/2026-03-08/
rm -rf logs/2026-03-08/
```

---

## Troubleshooting

### Q: Admin dashboard shows "Failed to load sessions"

**A:** Check that:
1. Backend is running (`python -m uvicorn main:app`)
2. `backend/logs/` directory exists
3. Check browser console for network errors
4. Verify CORS is configured for your origin

### Q: Screenshots not loading

**A:** Check that:
1. Screenshot files exist in `logs/<date>/<session_id>/screenshots/`
2. Backend is serving `/logs` path correctly
3. Screenshot paths in `screenshots_meta.json` are correct

### Q: Session created but no logs appear

**A:** Check that:
1. Session logger is being used in your code
2. `log_nova_act()`, `log_phase()` calls are made
3. Logs directory has write permissions: `chmod -R 755 backend/logs`

---

## Best Practices

1. **Always call `finalize_session()`** — even if search fails, ensures end timestamp is recorded

2. **Log errors immediately** — don't wait, use `logger.log_error()` as soon as error occurs

3. **Capture screenshots at key phases** — helps debug visually what happened

4. **Include context in phase logs** — add `details` dict with counts, durations, status

5. **Regular backups** — session data is persistent, back up `logs/` directory regularly

6. **Review failed sessions first** — sort by status="failed" to debug issues

---

## Future Enhancements

Potential additions:
- [ ] Export session to ZIP for sharing
- [ ] Compare two sessions side-by-side
- [ ] Search across all logs (global search)
- [ ] Replay screenshots as video/GIF
- [ ] Automated alerts for errors
- [ ] Performance analytics across sessions
- [ ] CSV export of execution timeline
- [ ] Webhook notifications for failures
