"""
Session-based logging system for tracking flights searches and Nova Act workflows.

Creates structured logs at: logs/<YYYY-MM-DD>/<session_id>/
  - metadata.json: session info, timestamps, search params
  - nova_act_logs.txt: Nova Act workflow logs
  - screenshots/: captured screenshots with timestamps
  - execution.json: timing data, phase durations, errors
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import uuid
import logging

log = logging.getLogger(__name__)


class SessionLogger:
    """Manages session-based logging for flight searches."""

    def __init__(self, base_logs_dir: str = "backend/logs"):
        self.base_logs_dir = Path(base_logs_dir)
        self.base_logs_dir.mkdir(parents=True, exist_ok=True)
        self.current_session = None

    def create_session(
        self,
        from_city: str,
        to_city: str,
        date: str,
        travel_class: str,
        agents: list,
        filters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a new search session.

        Returns: session_id
        """
        session_id = str(uuid.uuid4())[:8]
        today = datetime.now().strftime("%Y-%m-%d")

        # Create session directory structure
        self.session_dir = self.base_logs_dir / today / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self.session_dir / "screenshots").mkdir(exist_ok=True)

        # Write metadata
        metadata = {
            "session_id": session_id,
            "date": today,
            "timestamp_start": datetime.now().isoformat(),
            "search_params": {
                "from_city": from_city,
                "to_city": to_city,
                "travel_date": date,
                "travel_class": travel_class,
                "agents": agents,
                "filters": filters or {},
            },
            "status": "in_progress",
        }

        with open(self.session_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        self.current_session = session_id
        log.info(f"Created session: {session_id} at {self.session_dir}")

        return session_id

    def log_nova_act(self, workflow_id: str, agent_name: str, logs_content: str):
        """
        Log Nova Act workflow logs for an agent.
        """
        if not self.session_dir:
            return

        nova_logs_file = self.session_dir / f"nova_act_{agent_name}.log"
        with open(nova_logs_file, "a") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Workflow: {workflow_id}\n")
            f.write(f"Agent: {agent_name}\n")
            f.write(f"Time: {datetime.now().isoformat()}\n")
            f.write(f"{'='*60}\n")
            f.write(logs_content)
            f.write("\n")

    def capture_screenshot(
        self, agent_name: str, phase: str, screenshot_path: str, description: str = ""
    ):
        """
        Copy a screenshot to the session directory.

        Returns: relative path to copied screenshot
        """
        if not self.session_dir or not Path(screenshot_path).exists():
            return None

        timestamp = datetime.now().strftime("%H-%M-%S")
        dest_name = f"{agent_name}_{phase}_{timestamp}.png"
        dest_path = self.session_dir / "screenshots" / dest_name

        try:
            shutil.copy2(screenshot_path, dest_path)

            # Log screenshot metadata
            screenshots_meta = self.session_dir / "screenshots_meta.json"
            meta = []
            if screenshots_meta.exists():
                with open(screenshots_meta) as f:
                    meta = json.load(f)

            meta.append({
                "filename": dest_name,
                "agent": agent_name,
                "phase": phase,
                "timestamp": datetime.now().isoformat(),
                "description": description,
            })

            with open(screenshots_meta, "w") as f:
                json.dump(meta, f, indent=2)

            return str(dest_path.relative_to(self.base_logs_dir.parent))
        except Exception as e:
            log.error(f"Failed to capture screenshot: {e}")
            return None

    def log_phase(self, phase: str, agent: str, duration_ms: int, status: str, details: Dict = None):
        """Log phase execution details."""
        if not self.session_dir:
            return

        exec_file = self.session_dir / "execution.json"
        execution = []

        if exec_file.exists():
            with open(exec_file) as f:
                execution = json.load(f)

        execution.append({
            "phase": phase,
            "agent": agent,
            "duration_ms": duration_ms,
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "details": details or {},
        })

        with open(exec_file, "w") as f:
            json.dump(execution, f, indent=2)

    def log_error(self, error: str, context: str = "", agent: str = ""):
        """Log an error that occurred during the session."""
        if not self.session_dir:
            return

        errors_file = self.session_dir / "errors.json"
        errors = []

        if errors_file.exists():
            with open(errors_file) as f:
                errors = json.load(f)

        errors.append({
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "context": context,
            "error": error,
        })

        with open(errors_file, "w") as f:
            json.dump(errors, f, indent=2)

    def finalize_session(self, status: str = "completed", summary: Dict = None):
        """Finalize the session and write metadata."""
        if not self.session_dir:
            return

        metadata_file = self.session_dir / "metadata.json"

        if metadata_file.exists():
            with open(metadata_file) as f:
                metadata = json.load(f)

            metadata["status"] = status
            metadata["timestamp_end"] = datetime.now().isoformat()
            metadata["summary"] = summary or {}

            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

        log.info(f"Session {self.current_session} finalized: {status}")


# Global session logger instance
_session_logger = None


def get_session_logger() -> SessionLogger:
    """Get the global session logger instance."""
    global _session_logger
    if _session_logger is None:
        _session_logger = SessionLogger()
    return _session_logger
