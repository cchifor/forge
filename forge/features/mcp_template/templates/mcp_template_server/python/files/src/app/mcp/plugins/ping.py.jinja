"""Sample MCP integration plugin — proves the wiring.

Replace with a real integration. The ``slug`` is the plugin identifier
that shows up in MCP tool namespacing; pick a reverse-DNS form.
"""

from __future__ import annotations

from weld.mcp_template import BasePlugin, PluginContext, ToolDef


class PingPlugin(BasePlugin):
    slug = "{{ project_slug }}.ping"

    async def list_tools(self, ctx: PluginContext) -> list[ToolDef]:
        return [
            ToolDef(
                name="ping",
                description="Health-check the {{ project_title }} service.",
                input_schema={"type": "object", "properties": {}},
                handler=self._ping,
            )
        ]

    async def _ping(self, args: dict, ctx: PluginContext) -> dict:
        return {"ok": True, "service": "{{ project_slug }}"}
