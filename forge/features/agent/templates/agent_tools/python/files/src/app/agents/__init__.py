"""Agent infrastructure: tool registry + pre-baked tools.

This package ships the foundation for an AI-agent feature. A later feature
(``agent_streaming`` + a chosen LLM provider) can iterate over
``tool_registry`` to expose tools to the model. Right now the tools are
pure Python callables — the /api/v1/tools endpoint lists them for
observability.
"""

from app.agents.tool import Tool, ToolRegistry, tool_registry

__all__ = ["Tool", "ToolRegistry", "tool_registry"]
