"""FastAPI router for MCP tool discovery + invocation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class McpTool(BaseModel):
    """One tool surfaced by an MCP server."""

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]


class McpInvokeRequest(BaseModel):
    server: str
    tool: str
    input: dict[str, Any]
    approval_token: str | None = None


class McpInvokeResponse(BaseModel):
    ok: bool
    output: Any
    error: str | None = None


router = APIRouter(prefix="/mcp", tags=["mcp"])


_registry_cache: list[McpTool] | None = None


def _config_path() -> Path:
    return Path(os.getenv("MCP_CONFIG_PATH", "mcp.config.json")).resolve()


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        return {"version": 1, "servers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/tools", response_model=list[McpTool])
async def list_tools() -> list[McpTool]:
    """Return every tool advertised by every connected MCP server.

    Alpha (1.0.0a1): returns an empty list when no servers are configured.
    Real tool discovery (spawning MCP stdio/websocket clients) lands in
    1.0.0a3 alongside the approval UI.
    """
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    config = _load_config()
    # Spawning MCP clients is non-trivial — placeholder for now.
    servers = config.get("servers") or {}
    _registry_cache = []
    for server_name in sorted(servers):
        _registry_cache.append(
            McpTool(
                server=server_name,
                name=f"{server_name}:placeholder",
                description=f"Placeholder tool — real discovery lands in 1.0.0a3.",
                input_schema={"type": "object", "additionalProperties": True},
            )
        )
    return _registry_cache


@router.post("/invoke", response_model=McpInvokeResponse)
async def invoke_tool(req: McpInvokeRequest) -> McpInvokeResponse:
    """Proxy a tool call to the named server with approval-mode enforcement.

    Alpha behavior: returns an error payload explaining that real MCP
    invocation requires the 1.0.0a3 spawn-and-proxy implementation.
    Exists so the frontend ApprovalDialog has a stable endpoint to
    integrate against today.
    """
    config = _load_config()
    servers = config.get("servers") or {}
    if req.server not in servers:
        raise HTTPException(
            status_code=404,
            detail=f"MCP server {req.server!r} is not configured (check mcp.config.json).",
        )
    return McpInvokeResponse(
        ok=False,
        output=None,
        error="MCP invocation not yet wired (1.0.0a1 stub). Tool registry is available at /mcp/tools.",
    )
