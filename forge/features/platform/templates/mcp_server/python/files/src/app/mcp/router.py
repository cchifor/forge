"""FastAPI router for MCP tool discovery + invocation.

Backed by ``mcp/client.py``'s stdio JSON-RPC client. The router owns a
process-wide ``McpRegistry`` spun up at app startup (via the lifespan
hook injected by this fragment's inject.yaml) and torn down at shutdown.

Endpoints:
    GET  /mcp/tools    — aggregated list of tools across every
                         successfully-started MCP server
    POST /mcp/invoke   — proxy a tool call; the ``approval_token`` field
                         is reserved for the Phase 3.4 approval UI
                         integration and is passed through verbatim for
                         now (auditable but unenforced)
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from weld.fastapi.security.auth import get_current_user

from app.mcp.audit import (
    AuditEntry,
    hash_input,
    mint_approval_token,
    read_last_n,
    record_invocation,
    verify_approval_token,
)
from app.mcp.client import McpRegistry, load_registry_from_config

logger = logging.getLogger(__name__)


class McpTool(BaseModel):
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]
    approval_mode: str


class McpInvokeRequest(BaseModel):
    server: str
    tool: str
    input: dict[str, Any]
    approval_token: str | None = None


class McpInvokeResponse(BaseModel):
    ok: bool
    output: Any = None
    error: str | None = None


# Every /mcp route requires an authenticated user: the server exposes tool
# invocation (subprocess execution), approval-token minting, and an audit
# log of user identities. ``get_current_user`` raises 401 when no valid
# bearer token is present (``oauth2_scheme`` alone is auto_error=False and
# would NOT gate). Enabling the MCP server (platform.mcp OR
# agent.mode=tool_calling) requires auth.mode=generate (enforced in the
# resolver), so the auth stack is always present here.
router = APIRouter(
    prefix="/mcp", tags=["mcp"], dependencies=[Depends(get_current_user)]
)


def _config_path() -> Path:
    return Path(os.getenv("MCP_CONFIG_PATH", "mcp.config.json")).resolve()


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        return {"version": 1, "servers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _get_registry(request: Request) -> McpRegistry:
    """Fetch (or lazily build) the registry attached to app.state."""
    registry = getattr(request.app.state, "mcp_registry", None)
    if registry is None:
        registry = load_registry_from_config(_load_config())
        request.app.state.mcp_registry = registry
    return registry


@router.get("/tools", response_model=list[McpTool])
async def list_tools(request: Request) -> list[McpTool]:
    """Aggregate tools from every started MCP server."""
    registry = _get_registry(request)
    await registry.start_all()
    config = _load_config()
    default_mode = str(config.get("defaultApprovalMode") or "prompt-once")
    server_configs = config.get("servers") or {}

    out: list[McpTool] = []
    for server_name in registry.live_servers():
        client = registry.get(server_name)
        if client is None:
            continue
        try:
            tools = await client.list_tools()
        except Exception as exc:  # noqa: BLE001
            logger.warning("tools/list failed for %s: %s", server_name, exc)
            continue
        srv_mode = str(
            (server_configs.get(server_name) or {}).get("approvalMode")
            or default_mode
        )
        for tool in tools:
            out.append(
                McpTool(
                    server=server_name,
                    name=str(tool.get("name", "")),
                    description=str(tool.get("description", "")),
                    input_schema=tool.get("inputSchema") or {"type": "object"},
                    approval_mode=srv_mode,
                )
            )
    return out


class McpMintRequest(BaseModel):
    """Request to mint an approval token after the user clicks Approve."""

    server: str
    tool: str
    input: dict[str, Any]


class McpMintResponse(BaseModel):
    token: str


@router.post("/approval/mint", response_model=McpMintResponse)
async def mint_approval(req: McpMintRequest) -> McpMintResponse:
    """Issue a signed approval token tied to (server, tool, input-hash).

    The frontend's ApprovalDialog calls this after the user approves and
    then includes the returned token in the subsequent ``/mcp/invoke``
    request. Tokens expire after an hour; the signature binds the
    decision to the specific tool + payload so a token granted for one
    call cannot be replayed against a different input.
    """
    token = mint_approval_token(server=req.server, tool=req.tool, input_payload=req.input)
    return McpMintResponse(token=token)


@router.post("/invoke", response_model=McpInvokeResponse)
async def invoke_tool(
    req: McpInvokeRequest,
    request: Request,
    user: Annotated[Any, Depends(get_current_user)],
) -> McpInvokeResponse:
    """Proxy a tool call to the named server (audit + approval enforced).

    Pipeline:
      1. Resolve the tool's approval mode from the live tool list.
      2. If the mode is not ``auto``, verify the approval_token against
         (server, tool, input) — reject + audit on failure.
      3. Forward to the MCP client and relay the result.
      4. Record one audit entry per invocation (approved / denied /
         rejected-bad-token / auto / error).
    """
    registry = _get_registry(request)
    await registry.start_all()
    client = registry.get(req.server)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail=f"MCP server {req.server!r} is not started (check mcp.config.json + server logs).",
        )

    config = _load_config()
    default_mode = str(config.get("defaultApprovalMode") or "prompt-once")
    server_config = (config.get("servers") or {}).get(req.server) or {}
    approval_mode = str(server_config.get("approvalMode") or default_mode)

    # Identity comes from the verified token (the router-level
    # get_current_user gate), NOT the spoofable x-gatekeeper-user-id header.
    user_id = str(user.id) if user is not None else None
    audit_ts = time.time()
    audit_hash = hash_input(req.input)

    if approval_mode != "auto":
        token = req.approval_token or ""
        if not verify_approval_token(
            token, server=req.server, tool=req.tool, input_payload=req.input
        ):
            record_invocation(
                AuditEntry(
                    timestamp=audit_ts,
                    user_id=user_id,
                    server=req.server,
                    tool=req.tool,
                    input_hash=audit_hash,
                    decision="rejected-bad-token",
                    error="approval_token missing or invalid",
                )
            )
            raise HTTPException(
                status_code=401,
                detail="Approval token missing or invalid. Call /mcp/approval/mint first.",
            )

    decision = "approved" if approval_mode != "auto" else "auto"
    try:
        result = await client.call_tool(req.tool, req.input)
    except Exception as exc:  # noqa: BLE001
        record_invocation(
            AuditEntry(
                timestamp=audit_ts,
                user_id=user_id,
                server=req.server,
                tool=req.tool,
                input_hash=audit_hash,
                decision=decision,
                error=str(exc),
            )
        )
        return McpInvokeResponse(ok=False, error=str(exc))

    record_invocation(
        AuditEntry(
            timestamp=audit_ts,
            user_id=user_id,
            server=req.server,
            tool=req.tool,
            input_hash=audit_hash,
            decision=decision,
        )
    )
    return McpInvokeResponse(ok=True, output=result)


class McpAuditEntry(BaseModel):
    """One audit-log entry as written by :func:`app.mcp.audit.record_invocation`.

    Fields mirror the on-disk JSONL shape verbatim. New columns added
    to the write path (e.g. ``tool_call_id``, ``approval_mode``,
    ``correlation_id`` — RFC-014 deferred) should grow this model as
    optional, never repurpose existing field semantics.

    ``model_config = {"extra": "allow"}`` keeps the response forward-
    compatible: when the write path adds fields ahead of this model's
    next bump, they still surface to API clients rather than getting
    silently dropped by Pydantic v2's default-strict serialization.
    """

    model_config = {"extra": "allow"}

    # Mirror the on-disk JSONL shape: ``ts`` is a float epoch and
    # ``user_id`` is null for entries recorded without an authenticated
    # subject (e.g. auto-approved). Declaring them str / non-optional made
    # GET /mcp/audit 500 on real entries.
    ts: float
    user_id: str | None = None
    server: str
    tool: str
    input_hash: str
    decision: str
    error: str | None = None


class McpAuditResponse(BaseModel):
    """Page of audit entries returned by ``GET /mcp/audit``."""

    entries: list[McpAuditEntry]


@router.get("/audit", response_model=McpAuditResponse)
async def list_audit(
    limit: int = Query(
        default=50,
        ge=1,
        le=1000,
        description="Maximum number of entries to return, most-recent-first.",
    ),
) -> McpAuditResponse:
    """Return the last ``limit`` audit-log entries, most-recent-first.

    Operators + debug UIs use this to inspect MCP tool-call decisions
    written by :func:`app.mcp.audit.record_invocation`. The endpoint
    is additive — the write path is unchanged. Each entry mirrors the
    on-disk JSONL shape: ``{ts, user_id, server, tool, input_hash,
    decision, error}``. Missing log file returns an empty list (not
    an error: that's the "no calls yet" case). Storage-backend
    failures surface as 500 so monitoring catches them.

    **Deferred fields:** ``tool_call_id``, ``approval_mode``, and
    ``correlation_id`` are spec-mentioned but not yet on the write
    path. Adding them is a follow-up that extends
    ``record_invocation`` (and bumps :class:`McpAuditEntry` to declare
    each as optional). Until then this endpoint returns the JSONL
    fields verbatim.

    **Memory cost:** ``read_last_n`` parses the entire log file into
    memory before slicing. Acceptable because the JSONL is externally
    rotated (see ``audit.py`` module docstring) and bounded to MB-
    scale in production. If rotation is mis-configured and the file
    grows to GB-scale, this endpoint will OOM the worker — that's a
    deployment misconfiguration to surface in monitoring, not an
    endpoint bug.
    """
    try:
        entries = read_last_n(limit)
    except OSError as exc:
        logger.warning("MCP audit read failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="MCP audit storage backend unavailable.",
        ) from exc
    return McpAuditResponse(entries=entries)
