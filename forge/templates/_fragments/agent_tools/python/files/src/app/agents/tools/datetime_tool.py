"""`current_datetime` — returns the current UTC time in ISO-8601."""

from __future__ import annotations

from datetime import UTC, datetime

from app.agents.tool import Tool, tool_registry


async def _current_datetime() -> str:
    """Return the current UTC time in ISO-8601 format (e.g. 2026-04-18T14:22:11Z)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


tool = Tool(
    name="current_datetime",
    description="Return the current UTC datetime in ISO-8601 format.",
    input_schema={"type": "object", "properties": {}, "required": []},
    handler=_current_datetime,
    tags=("utility",),
)

if tool.name not in tool_registry:
    tool_registry.register(tool)
