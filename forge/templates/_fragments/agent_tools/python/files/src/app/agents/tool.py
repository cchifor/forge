"""Tool base class and process-wide registry.

A Tool is a small async callable with a name, description, and JSON schema
describing its input. Tools self-register via :class:`ToolRegistry` so an
LLM layer (pydantic-ai, LangChain, ...) can enumerate and invoke them
without hardcoding references.

Minimal shape — deliberately framework-agnostic so the same tools can be
handed to any of the AI frameworks we may ship in a later feature.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tool:
    """A single tool the agent can invoke.

    ``handler`` takes keyword arguments matching ``input_schema`` and returns
    a JSON-serializable value. Keep the signature simple — LLMs do better
    with flat, typed arguments than with nested object bags.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]
    tags: tuple[str, ...] = field(default_factory=tuple)

    async def invoke(self, **kwargs: Any) -> Any:
        return await self.handler(**kwargs)


class ToolRegistry:
    """In-memory tool registry. Not thread-safe by design — tools register
    once at import time."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as e:
            raise LookupError(f"Unknown tool: {name!r}") from e

    def names(self) -> list[str]:
        return sorted(self._tools)

    def list(self) -> list[Tool]:
        return [self._tools[n] for n in self.names()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools


# Process-wide singleton. Import from anywhere:
#     from app.agents import tool_registry
tool_registry = ToolRegistry()


def install_default_tools() -> None:
    """Import (and thereby register) the built-in tools.

    Safe to call multiple times — import is idempotent; re-calling does
    nothing because the tool modules guard their registration.
    """
    from app.agents.tools import datetime_tool  # noqa: F401
    from app.agents.tools import web_search_tool  # noqa: F401
