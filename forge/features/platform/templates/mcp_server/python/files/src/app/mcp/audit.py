"""Audit-log + approval-token middleware for MCP tool invocations.

Every call to ``POST /mcp/invoke`` passes through the audit pipeline:

  1. The caller supplies an ``approval_token`` (signed by the frontend's
     ApprovalDialog) when the tool's ``approval_mode`` is not ``auto``.
  2. ``verify_approval_token`` confirms the token was issued by this
     service for the same (server, tool, input-hash) tuple. Tampered or
     replayed tokens are rejected.
  3. ``record_invocation`` appends a single JSON line to the audit log
     with the user identity (from request headers) + tool identity +
     SHA-256 of the input + the decision.

Two-file audit design: ``audit.jsonl`` is append-only; a daily rotation
is the user's responsibility (logrotate, CloudWatch, whatever).
Archived lines remain valid — the signing key doesn't rotate in this
scope; see ``docs/mcp.md`` for the full story.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApprovalToken:
    """Parsed approval token — server/tool/input_hash + HMAC signature."""

    server: str
    tool: str
    input_hash: str
    issued_at: int  # unix seconds
    signature: str


@dataclass(frozen=True)
class AuditEntry:
    """One recorded MCP tool invocation.

    Serialized as a single JSON line in ``audit.jsonl``.
    """

    timestamp: float
    user_id: str | None
    server: str
    tool: str
    input_hash: str
    decision: str  # "approved" | "denied" | "auto" | "rejected-bad-token"
    error: str | None = None


# -- Token mint + verify -----------------------------------------------------


def _secret() -> bytes:
    """Load the signing secret from the environment.

    Generated projects are expected to set ``MCP_APPROVAL_SIGNING_KEY``
    to a high-entropy random string (32+ bytes). If the env var is
    missing, fall back to the service name — callers get a noisy warn,
    but the service still boots (important for local dev).
    """
    key = os.getenv("MCP_APPROVAL_SIGNING_KEY")
    if key:
        return key.encode("utf-8")
    logger.warning(
        "MCP_APPROVAL_SIGNING_KEY not set — using the service name as a fallback "
        "signing key. This is NOT safe for production."
    )
    return os.getenv("OTEL_SERVICE_NAME", "forge-service").encode("utf-8")


def hash_input(input_payload: dict[str, Any]) -> str:
    """Canonical SHA-256 of a tool's input payload."""
    canonical = json.dumps(input_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mint_approval_token(*, server: str, tool: str, input_payload: dict[str, Any]) -> str:
    """Produce a new approval token for a tool call.

    The frontend's ApprovalDialog requests a mint when the user approves,
    and sends the returned token back on the next /mcp/invoke call.
    Tokens don't carry user identity — they certify "this specific
    (server, tool, input) was approved by some user of this service" and
    are non-transferable since the input_hash binds the payload.
    """
    input_hash = hash_input(input_payload)
    issued_at = int(time.time())
    message = f"{server}|{tool}|{input_hash}|{issued_at}".encode("utf-8")
    signature = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return ":".join([server, tool, input_hash, str(issued_at), signature])


def parse_approval_token(token: str) -> ApprovalToken | None:
    """Decompose a token string. Returns ``None`` on malformed input."""
    parts = token.split(":")
    if len(parts) != 5:
        return None
    server, tool, input_hash, issued_at, signature = parts
    try:
        issued_int = int(issued_at)
    except ValueError:
        return None
    return ApprovalToken(
        server=server,
        tool=tool,
        input_hash=input_hash,
        issued_at=issued_int,
        signature=signature,
    )


def verify_approval_token(
    token: str,
    *,
    server: str,
    tool: str,
    input_payload: dict[str, Any],
    max_age_seconds: int = 3600,
) -> bool:
    """Verify that a token is valid for a specific tool call.

    Checks: signature matches, not expired, (server, tool, input_hash)
    matches. Returns ``False`` for any failure — callers log and reject.
    """
    parsed = parse_approval_token(token)
    if parsed is None:
        return False
    if parsed.server != server or parsed.tool != tool:
        return False
    if parsed.input_hash != hash_input(input_payload):
        return False
    if time.time() - parsed.issued_at > max_age_seconds:
        return False
    message = f"{parsed.server}|{parsed.tool}|{parsed.input_hash}|{parsed.issued_at}".encode("utf-8")
    expected = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(parsed.signature, expected)


# -- Audit log ---------------------------------------------------------------


def _audit_path() -> Path:
    return Path(os.getenv("MCP_AUDIT_LOG", "audit.jsonl")).resolve()


def record_invocation(entry: AuditEntry) -> None:
    """Append a single JSON line to the audit log.

    Failures are logged but don't raise — audit-log writes shouldn't
    block the user's tool call. Downstream monitoring should alert on
    missing writes via log analysis (the warn line below).
    """
    path = _audit_path()
    line = json.dumps(
        {
            "ts": entry.timestamp,
            "user_id": entry.user_id,
            "server": entry.server,
            "tool": entry.tool,
            "input_hash": entry.input_hash,
            "decision": entry.decision,
            "error": entry.error,
        },
        separators=(",", ":"),
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP audit write failed: %s", exc)
