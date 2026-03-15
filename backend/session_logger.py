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
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import uuid
import logging

log = logging.getLogger(__name__)

_LOG_FMT = (
    "%(asctime)s.%(msecs)03d  "
    "%(levelname)-8s "
    "%(name)-24s "
    "%(funcName)-26s "
    ":%(lineno)-4d "
    "%(message)s"
)


class _TeeStream:
    """Mirrors writes to both the original stream and a log file.

    Used to capture Nova Act's stdout reasoning output (think/act/agentClick)
    alongside the regular Python logging output in the session log file.
    """

    def __init__(self, original, file_obj):
        self._original = original
        self._file = file_obj

    def write(self, data: str) -> int:
        self._original.write(data)
        try:
            self._file.write(data)
            self._file.flush()
        except Exception:
            pass
        return len(data)

    def flush(self) -> None:
        self._original.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def fileno(self):
        return self._original.fileno()

    def isatty(self) -> bool:
        return False

    # Proxy any other attribute lookups to the original stream
    def __getattr__(self, name):
        return getattr(self._original, name)


class SessionLogger:
    """Manages session-based logging for flight searches."""

    def __init__(self, base_logs_dir: str = "backend/logs"):
        self.base_logs_dir = Path(base_logs_dir)
        self.base_logs_dir.mkdir(parents=True, exist_ok=True)
        self.current_session = None
        self._file_handler: Optional[logging.FileHandler] = None
        self._log_file_obj = None          # raw file object for stdout/stderr tee
        self._orig_stdout = None
        self._orig_stderr = None

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

        # Attach a file handler to the root logger so ALL log output
        # (agents, Nova Act internals, normalizer, reasoner) is captured
        # in this session's log file automatically.
        self._attach_file_handler(self.session_dir / "nova_act_session.log")

        log.info(f"Created session: {session_id} at {self.session_dir}")

        return session_id

    def _attach_file_handler(self, log_path: Path) -> None:
        """Attach a FileHandler to the root logger and tee stdout/stderr.

        Captures both Python logging output AND Nova Act's direct stdout
        output (think/act/agentClick reasoning traces) in the session log.
        """
        self._detach_file_handler()  # Remove any previous handler first

        # Open a single shared file object used by both the logging handler
        # and the stdout/stderr tee so all output goes to one log file.
        log_file_obj = open(log_path, "a", encoding="utf-8", buffering=1)
        self._log_file_obj = log_file_obj

        # Python logging handler
        handler = logging.StreamHandler(log_file_obj)
        handler.setFormatter(logging.Formatter(_LOG_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
        logging.getLogger().addHandler(handler)
        self._file_handler = handler

        # Tee stdout and stderr so Nova Act's think/act/agentClick lines are captured
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _TeeStream(self._orig_stdout, log_file_obj)
        sys.stderr = _TeeStream(self._orig_stderr, log_file_obj)

    def _detach_file_handler(self) -> None:
        """Remove the session file handler and restore stdout/stderr."""
        if self._file_handler is not None:
            logging.getLogger().removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None

        # Restore original stdout/stderr before closing the file
        if self._orig_stdout is not None:
            sys.stdout = self._orig_stdout
            self._orig_stdout = None
        if self._orig_stderr is not None:
            sys.stderr = self._orig_stderr
            self._orig_stderr = None

        if self._log_file_obj is not None:
            try:
                self._log_file_obj.close()
            except Exception:
                pass
            self._log_file_obj = None

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

        # Detach the file handler so subsequent server requests don't keep writing here
        self._detach_file_handler()

        log.info(f"Session {self.current_session} finalized: {status}")

    async def generate_analysis_report_async(self) -> Optional[str]:
        """
        Auto-generate a phase-by-phase analysis report after session completes.
        Uses Nova Lite to parse the session logs and produce a structured report.
        Saves the report as session_analysis.md inside the session directory.
        Returns the report text, or None on failure.
        """
        if not self.session_dir or not self.session_dir.exists():
            return None

        try:
            import boto3

            # ── Collect session data ───────────────────────────────────────────
            metadata = {}
            md_file = self.session_dir / "metadata.json"
            if md_file.exists():
                metadata = json.loads(md_file.read_text())

            execution = []
            exec_file = self.session_dir / "execution.json"
            if exec_file.exists():
                execution = json.loads(exec_file.read_text())

            errors = []
            err_file = self.session_dir / "errors.json"
            if err_file.exists():
                errors = json.loads(err_file.read_text())

            # Truncate log to last 300 lines to stay within token limits
            log_lines = []
            log_file = self.session_dir / "nova_act_session.log"
            if log_file.exists():
                all_lines = log_file.read_text(encoding="utf-8").splitlines()
                log_lines = all_lines[-300:]

            # ── Load prompt template from file ─────────────────────────────────
            sp = metadata.get("search_params", {})
            prompt_path = Path(__file__).parent / "prompts" / "session_analysis_prompt.md"
            prompt_template = prompt_path.read_text(encoding="utf-8")

            prompt = (
                prompt_template
                .replace("{{metadata}}", json.dumps(metadata, indent=2))
                .replace("{{execution}}", json.dumps(execution, indent=2))
                .replace("{{errors}}", json.dumps(errors, indent=2))
                .replace("{{log_line_count}}", str(len(log_lines)))
                .replace("{{log_lines}}", "\n".join(log_lines))
                .replace("{{session_id}}", metadata.get("session_id", "?"))
                .replace("{{status}}", metadata.get("status", "?"))
                .replace("{{from_city}}", sp.get("from_city", "?"))
                .replace("{{to_city}}", sp.get("to_city", "?"))
                .replace("{{travel_date}}", sp.get("travel_date", "?"))
                .replace("{{travel_class}}", sp.get("travel_class", "?"))
                .replace("{{agents}}", ", ".join(sp.get("agents", [])))
            )

            # ── Call Nova Pro (stronger reasoning for log analysis) ────────────
            # Nova Lite handles extraction but struggles with multi-step correlation
            # across phases. Nova Pro matches what we use for flight reasoning.
            client = boto3.client(
                "bedrock-runtime",
                region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            )
            body = {
                "schemaVersion": "messages-v1",
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {"maxTokens": 2048, "temperature": 0.1},
            }
            response = client.invoke_model(
                modelId="us.amazon.nova-pro-v1:0",
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            report = result["output"]["message"]["content"][0]["text"].strip()

            # ── Save report ────────────────────────────────────────────────────
            report_file = self.session_dir / "session_analysis.md"
            report_file.write_text(
                f"# Session Analysis — {metadata.get('session_id', '')}\n"
                f"Generated: {datetime.now().isoformat()}\n\n"
                f"{report}",
                encoding="utf-8",
            )
            log.info("Session analysis report saved: %s", report_file)
            return report

        except Exception as e:
            log.error("Failed to generate session analysis report: %s", e)
            # Save a minimal error report so the tab still shows something
            try:
                err_report = (
                    f"# Session Analysis — {self.current_session}\n\n"
                    f"⚠️ Auto-analysis failed: {e}\n\n"
                    f"Run `/analyze-session {self.current_session}` manually in Claude Code."
                )
                (self.session_dir / "session_analysis.md").write_text(err_report, encoding="utf-8")
            except Exception:
                pass
            return None


# Global session logger instance
_session_logger = None


def get_session_logger() -> SessionLogger:
    """Get the global session logger instance."""
    global _session_logger
    if _session_logger is None:
        _session_logger = SessionLogger()
    return _session_logger
