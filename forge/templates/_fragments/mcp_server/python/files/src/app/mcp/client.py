"""JSON-RPC over stdio client for Model Context Protocol servers.

Spawns the subprocess described by an ``mcp.config.json`` server entry
and speaks the newline-delimited JSON-RPC 2.0 protocol used by MCP.
Discovery + tool invocation are the two operations the router needs;
initialisation runs automatically on first use.

Not a general-purpose MCP implementation — the goal is "forge-generated
services can invoke MCP tools over stdio without pulling in a heavier
client library". For richer transports (websockets, SSE), switch to the
official ``mcp`` client when it stabilises.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    """One entry from ``mcp.config.json``'s ``servers`` table."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    approval_mode: str = "prompt-once"


class McpStdioClient:
    """Persistent JSON-RPC client over an MCP server subprocess.

    Lifecycle:
      * ``start()`` spawns the process and completes the MCP initialize
        handshake
      * ``list_tools()`` returns the advertised tools
      * ``call_tool(name, arguments)`` invokes a tool and returns the
        server's response (content blocks)
      * ``stop()`` terminates the subprocess cleanly

    The client is intentionally sequential — one in-flight request per
    server. Pipelining isn't needed for forge's first MCP scope.
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._initialized = False

    async def start(self) -> None:
        """Spawn the subprocess and complete the MCP initialize handshake."""
        if self._process is not None:
            return
        env = {**os.environ, **self.config.env}
        self._process = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        await self._initialize()

    async def _initialize(self) -> None:
        await self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "forge", "version": "1.0.0a3"},
            },
        )
        # The spec requires a notification after initialize, not a request.
        await self._notify("notifications/initialized", {})
        self._initialized = True

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the server's ``tools/list`` result."""
        result = await self._rpc("tools/list", {})
        return list(result.get("tools", []))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``tools/call`` on the server."""
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})

    async def stop(self) -> None:
        """Terminate the subprocess."""
        if self._process is None:
            return
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            self._process.kill()
        finally:
            self._process = None
            self._initialized = False

    # -- low-level JSON-RPC ----------------------------------------------

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a request and wait for the matching response."""
        async with self._lock:
            assert self._process is not None
            request_id = self._next_id
            self._next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
            line = json.dumps(payload) + "\n"
            assert self._process.stdin is not None
            self._process.stdin.write(line.encode("utf-8"))
            await self._process.stdin.drain()

            # Skip any notifications from the server while waiting for the
            # response to our request id.
            while True:
                assert self._process.stdout is not None
                raw = await self._process.stdout.readline()
                if not raw:
                    raise RuntimeError(
                        f"MCP server {self.config.name!r} closed stdout unexpectedly"
                    )
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if msg.get("id") != request_id:
                    # Notification or a different request — ignore.
                    continue
                if "error" in msg:
                    raise RuntimeError(
                        f"MCP {method} on {self.config.name!r}: {msg['error'].get('message', 'error')}"
                    )
                return msg.get("result", {})

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        assert self._process is not None and self._process.stdin is not None
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        line = json.dumps(payload) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()


class McpRegistry:
    """Process-lifecycle manager for every configured MCP server.

    One instance per application; shared across requests. ``start_all``
    spawns every server in the config concurrently; ``stop_all`` tears
    them down at shutdown.
    """

    def __init__(self, config: dict[str, McpServerConfig]) -> None:
        self._config = config
        self._clients: dict[str, McpStdioClient] = {}
        self._started = False

    async def start_all(self) -> None:
        if self._started:
            return
        for name, server_config in self._config.items():
            client = McpStdioClient(server_config)
            try:
                await client.start()
                self._clients[name] = client
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP server %r failed to start: %s", name, exc)
        self._started = True

    async def stop_all(self) -> None:
        for client in self._clients.values():
            try:
                await client.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP server stop failed: %s", exc)
        self._clients.clear()
        self._started = False

    def get(self, name: str) -> McpStdioClient | None:
        return self._clients.get(name)

    def live_servers(self) -> list[str]:
        return sorted(self._clients)


def load_registry_from_config(config: dict[str, Any]) -> McpRegistry:
    """Build a registry from a parsed ``mcp.config.json`` document."""
    servers: dict[str, McpServerConfig] = {}
    for name, raw in (config.get("servers") or {}).items():
        if not isinstance(raw, dict):
            continue
        servers[name] = McpServerConfig(
            name=name,
            command=str(raw.get("command", "")),
            args=list(raw.get("args") or []),
            env=dict(raw.get("env") or {}),
            approval_mode=str(
                raw.get("approvalMode")
                or config.get("defaultApprovalMode")
                or "prompt-once"
            ),
        )
    return McpRegistry(servers)
