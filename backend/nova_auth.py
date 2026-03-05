"""
nova_auth.py — Nova Act workflow definition helper (IAM mode).

The Workflow class requires a workflow definition name registered in AWS.
This module handles check-then-create with in-memory caching to avoid
repeat AWS API calls within the same process lifetime.

IAM mode ONLY — NOVA_ACT_API_KEY must NOT be set (it conflicts with IAM auth).
Each agent pops the env var before starting its Workflow session.
"""

import os
import re
import sys
import boto3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logger import get_logger

log = get_logger(__name__)

# In-memory cache: workflow names confirmed to exist in AWS this process
_workflow_cache: set[str] = set()

# Workflow name rules enforced by Nova Act: lowercase letters, numbers, hyphens only
_WORKFLOW_NAME_RE = re.compile(r'^[a-z0-9-]+$')


def _workflow_exists(client, name: str) -> bool:
    """Return True if the workflow definition already exists in AWS."""
    # Primary: fetch the specific definition by name
    try:
        client.get_workflow_definition(name=name)
        return True
    except Exception as e:
        err = str(e).lower()
        if any(kw in err for kw in ("not found", "does not exist", "resourcenotfound", "nosuch", "404")):
            return False
        # Unknown error on get — fall through to list-based check
        log.debug("get_workflow_definition raised unexpected error (%s), trying list fallback", e)

    # Fallback: list all definitions and scan by name
    try:
        response = client.list_workflow_definitions()
        # Response key may vary across SDK versions
        defs = (
            response.get("workflowDefinitions")
            or response.get("definitions")
            or response.get("items")
            or []
        )
        return any(d.get("name") == name for d in defs)
    except Exception as e2:
        log.warning("list_workflow_definitions failed: %s — will attempt create", e2)
        return False


def get_or_create_workflow_definition(name: str, s3_bucket: str | None = None) -> str:
    """
    Ensure a Nova Act workflow definition exists in AWS.

    Flow:
      1. Return immediately if name is cached (no AWS call)
      2. Check existence via get_workflow_definition (or list fallback)
      3. Create only if not found, wrapped in try/except for race conditions
      4. Cache the name so subsequent calls skip AWS entirely

    Args:
        name:      Workflow definition name — must match ^[a-z0-9-]+$
        s3_bucket: S3 bucket for workflow artifacts.
                   Falls back to NOVA_ACT_S3_BUCKET env var, then 'fair-wise'.

    Returns:
        The workflow name (same as input), ready to pass to Workflow(...).
    """
    if name in _workflow_cache:
        log.debug("Workflow definition cached (skipping AWS check): %s", name)
        return name

    if not _WORKFLOW_NAME_RE.match(name):
        raise ValueError(
            f"WORKFLOW_NAME must use lowercase letters, numbers, and hyphens only. Got: {name!r}"
        )

    client = boto3.client('nova-act')

    if _workflow_exists(client, name):
        log.info("Workflow definition exists, reusing: %s", name)
    else:
        bucket = s3_bucket or os.getenv("NOVA_ACT_S3_BUCKET", "fair-wise")
        try:
            response = client.create_workflow_definition(
                name=name,
                exportConfig={'s3BucketName': bucket},
            )
            log.info("Created workflow definition: %s → %s", name, response)
        except Exception as e:
            err = str(e).lower()
            # Race condition: another process created it between our check and create
            if any(kw in err for kw in ("already", "exists", "conflict", "duplicate", "resourceinuse")):
                log.info("Workflow definition created concurrently, reusing: %s", name)
            else:
                log.error("Failed to create workflow definition %s: %s", name, e)
                raise

    _workflow_cache.add(name)
    return name
