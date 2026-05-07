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
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.mcp.audit import (
    AuditEntry,
    hash_input,
    mint_approval_token,
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


router = APIRouter(prefix="/mcp", tags=["mcp"])


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
async def invoke_tool(req: McpInvokeRequest, request: Request) -> McpInvokeResponse:
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

    user_id = request.headers.get("x-gatekeeper-user-id")
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
