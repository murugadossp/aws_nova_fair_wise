"""
FareWise — Centralised logging configuration.

Import and call `get_logger(__name__)` in every module:

    from logger import get_logger
    log = get_logger(__name__)

    log.info("Starting search for '%s'", query)
    log.warning("Agent returned 0 results")
    log.error("Bedrock call failed: %s", e)

Output format:
    2026-03-04 10:23:45.123  INFO     nova.identifier          identify_from_text      :148  Querying Nova Lite for 'Sony WH-1000XM5'
    2026-03-04 10:23:46.004  ERROR    agents.amazon            search                  :81   Search failed for 'Sony WH-1000XM5': Connection refused
"""

import logging
import os
import sys
from datetime import datetime

# ── Format ─────────────────────────────────────────────────────────────────────
_FMT = (
    "%(asctime)s.%(msecs)03d  "
    "%(levelname)-8s "
    "%(name)-24s "
    "%(funcName)-26s "
    ":%(lineno)-4d "
    "%(message)s"
)
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# ── Level from env (default INFO; set LOG_LEVEL=DEBUG for verbose output) ──────
_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def _setup_root_logger() -> None:
    """Configure the root logger once at import time."""
    root = logging.getLogger()

    # Avoid adding duplicate handlers if this module is imported multiple times
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))

    root.addHandler(handler)
    root.setLevel(getattr(logging, _LEVEL, logging.INFO))

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)


_setup_root_logger()


def get_logger(name: str) -> logging.Logger:
    """
    Return a module-level logger.

    Usage:
        log = get_logger(__name__)   # e.g. "nova.identifier"
    """
    return logging.getLogger(name)


def add_agent_test_file_handler(agent_name: str) -> str:
    """
    Add a FileHandler so agent test logs are also written to a file.
    File: logs/agent_<agent_name>_<YYYY-MM-DD>_<HH-MM-SS>.log under the backend directory.
    Returns the absolute path of the log file.
    """
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(backend_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M-%S")
    safe_name = agent_name.lower().replace(" ", "_")
    log_filename = f"agent_{safe_name}_{date_str}_{time_str}.log"
    log_path = os.path.join(logs_dir, log_filename)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    logging.getLogger().addHandler(handler)
    return os.path.abspath(log_path)
