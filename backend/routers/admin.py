"""
Admin API endpoints for session logging and debugging.

Serves session data, logs, and screenshots from the logs directory structure.
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
from datetime import datetime

router = APIRouter(prefix="/api/admin", tags=["admin"])

LOGS_DIR = Path("backend/logs")


@router.get("/sessions")
async def get_sessions() -> List[Dict[str, Any]]:
    """
    Get all sessions organized by date.

    Returns list of sessions with basic info.
    """
    if not LOGS_DIR.exists():
        return []

    sessions = []

    # Iterate through date directories
    for date_dir in sorted(LOGS_DIR.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue

        # Iterate through session directories
        for session_dir in date_dir.iterdir():
            if not session_dir.is_dir():
                continue

            metadata_file = session_dir / "metadata.json"
            if not metadata_file.exists():
                continue

            try:
                with open(metadata_file) as f:
                    metadata = json.load(f)

                sessions.append({
                    "session_id": metadata.get("session_id"),
                    "date": metadata.get("date"),
                    "from_city": metadata.get("search_params", {}).get("from_city"),
                    "to_city": metadata.get("search_params", {}).get("to_city"),
                    "timestamp_start": metadata.get("timestamp_start"),
                    "status": metadata.get("status"),
                })
            except Exception as e:
                print(f"Error reading metadata from {metadata_file}: {e}")
                continue

    return sessions


@router.get("/sessions/{session_id}")
async def get_session_details(session_id: str) -> Dict[str, Any]:
    """
    Get detailed information for a specific session.

    Returns metadata, logs, execution timeline, screenshots, and errors.
    """
    # Find the session directory
    session_dir = None
    if LOGS_DIR.exists():
        for date_dir in LOGS_DIR.iterdir():
            if not date_dir.is_dir():
                continue
            candidate = date_dir / session_id
            if candidate.exists():
                session_dir = candidate
                break

    if not session_dir:
        raise HTTPException(status_code=404, detail="Session not found")

    # Read metadata
    metadata = None
    metadata_file = session_dir / "metadata.json"
    if metadata_file.exists():
        with open(metadata_file) as f:
            metadata = json.load(f)

    # Read logs — nova_act_session.log first (main log with Python + Nova Act stdout),
    # then any supplementary per-agent logs written via log_nova_act().
    logs = []
    log_files = sorted(
        session_dir.glob("nova_act_*.log"),
        key=lambda p: (0 if p.name == "nova_act_session.log" else 1, p.name),
    )
    for log_file in log_files:
        try:
            with open(log_file, encoding="utf-8") as f:
                content = f.read()
                logs.extend([line for line in content.split('\n') if line.strip()])
        except Exception as e:
            logs.append(f"Error reading {log_file.name}: {e}")

    # Read execution timeline
    execution = []
    exec_file = session_dir / "execution.json"
    if exec_file.exists():
        try:
            with open(exec_file) as f:
                execution = json.load(f)
        except Exception:
            pass

    # Get screenshots
    screenshots = []
    screenshots_meta_file = session_dir / "screenshots_meta.json"
    if screenshots_meta_file.exists():
        try:
            with open(screenshots_meta_file) as f:
                screenshots_meta = json.load(f)

            for meta in screenshots_meta:
                ss_path = session_dir / "screenshots" / meta.get("filename", "")
                if ss_path.exists():
                    screenshots.append({
                        "filename": meta.get("filename"),
                        "agent": meta.get("agent"),
                        "phase": meta.get("phase"),
                        "timestamp": meta.get("timestamp"),
                        "description": meta.get("description", ""),
                        # Make path relative to serve via static files
                        "path": f"/logs/{session_dir.parent.name}/{session_id}/screenshots/{meta.get('filename')}",
                    })
        except Exception:
            pass

    # Read errors
    errors = []
    errors_file = session_dir / "errors.json"
    if errors_file.exists():
        try:
            with open(errors_file) as f:
                errors = json.load(f)
        except Exception:
            pass

    # Read auto-generated analysis report
    analysis_report = None
    analysis_file = session_dir / "session_analysis.md"
    if analysis_file.exists():
        try:
            analysis_report = analysis_file.read_text(encoding="utf-8")
        except Exception:
            pass

    return {
        "session_id": session_id,
        "metadata": metadata,
        "logs": logs,
        "execution": execution,
        "screenshots": screenshots,
        "errors": errors,
        "analysis_report": analysis_report,
    }


@router.get("/summary")
async def get_summary() -> Dict[str, Any]:
    """
    Get summary statistics across all sessions.
    """
    if not LOGS_DIR.exists():
        return {
            "total_sessions": 0,
            "total_by_status": {},
            "total_by_agent": {},
            "recent_errors": 0,
        }

    total_sessions = 0
    by_status = {}
    by_agent = {}
    recent_errors = 0

    for date_dir in LOGS_DIR.iterdir():
        if not date_dir.is_dir():
            continue

        for session_dir in date_dir.iterdir():
            if not session_dir.is_dir():
                continue

            total_sessions += 1

            # Count by status
            metadata_file = session_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        status = metadata.get("status", "unknown")
                        by_status[status] = by_status.get(status, 0) + 1

                        # Count by agent
                        agents = metadata.get("search_params", {}).get("agents", [])
                        for agent in agents:
                            by_agent[agent] = by_agent.get(agent, 0) + 1
                except Exception:
                    pass

            # Count errors
            errors_file = session_dir / "errors.json"
            if errors_file.exists():
                try:
                    with open(errors_file) as f:
                        errors = json.load(f)
                        recent_errors += len(errors)
                except Exception:
                    pass

    return {
        "total_sessions": total_sessions,
        "total_by_status": by_status,
        "total_by_agent": by_agent,
        "recent_errors": recent_errors,
    }


@router.get("/pipeline-flow")
async def get_pipeline_flow() -> Dict[str, Any]:
    """Serve the FLIGHT_DATA_FLOW.md content for embedding in the admin dashboard."""
    md_path = Path("backend/FLIGHT_DATA_FLOW.md")
    if not md_path.exists():
        md_path = Path("FLIGHT_DATA_FLOW.md")
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="FLIGHT_DATA_FLOW.md not found")
    return {"content": md_path.read_text(encoding="utf-8")}
