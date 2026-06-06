"""Fragment unit tests for the vendored MCP template (weld-free).

Runs inside the generated project — imports ``app.mcp._template.*`` only,
never ``weld``. Covers: ToolDef + BasePlugin dispatch, build_server
returning a mountable Starlette app for one and many plugins (tenant
optional), and openapi_to_tools turning a spec into ToolDefs.
"""

from __future__ import annotations

import httpx
import pytest
from app.mcp._template import (
    AuthConfig,
    BasePlugin,
    PluginContext,
    ToolDef,
    build_server,
    openapi_to_tools,
)
from starlette.applications import Starlette


class _PingPlugin(BasePlugin):
    slug = "com.example.ping"

    async def list_tools(self, ctx: PluginContext) -> list[ToolDef]:
        return [
            ToolDef(
                name="ping",
                description="Ping",
                input_schema={"type": "object", "properties": {}},
                handler=self._ping,
            )
        ]

    async def _ping(self, args: dict, ctx: PluginContext) -> dict:
        return {"ok": True, "tenant": ctx.tenant_id}


def test_plugin_context_tenant_optional() -> None:
    """A single-tenant host can build a context with no tenant_id."""
    ctx = PluginContext(credentials={}, http=httpx.AsyncClient())
    assert ctx.tenant_id is None
    assert ctx.user_id is None
    assert ctx.integration_id is None


async def test_base_plugin_dispatches_by_name() -> None:
    plugin = _PingPlugin()
    ctx = PluginContext(credentials={}, http=httpx.AsyncClient())
    result = await plugin.call_tool("ping", {}, ctx)
    assert result == {"ok": True, "tenant": None}
    with pytest.raises(KeyError):
        await plugin.call_tool("nope", {}, ctx)
    await ctx.http.aclose()


async def _resolver(_headers: dict) -> PluginContext:
    return PluginContext(credentials={}, http=httpx.AsyncClient())


def test_build_server_single_plugin_returns_starlette() -> None:
    app = build_server(_PingPlugin(), context_resolver=_resolver)
    assert isinstance(app, Starlette)
    # The plugin is mounted under its slug.
    mount_paths = [r.path for r in app.routes]
    assert "/com.example.ping" in mount_paths


def test_build_server_multiple_plugins_each_mounted() -> None:
    class _Other(_PingPlugin):
        slug = "com.example.other"

    app = build_server((_PingPlugin(), _Other()), context_resolver=_resolver)
    assert isinstance(app, Starlette)
    mount_paths = {r.path for r in app.routes}
    assert {"/com.example.ping", "/com.example.other"} <= mount_paths


async def test_openapi_to_tools_builds_tooldefs() -> None:
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/things": {
                "get": {
                    "operationId": "listThings",
                    "summary": "List things",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                    ],
                }
            },
            "/things/{id}": {
                "get": {
                    "operationId": "get.thing",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                }
            },
        },
    }
    tools = await openapi_to_tools(spec=spec, auth_config=AuthConfig(type="bearer"))
    by_name = {t.name: t for t in tools}
    assert "listThings" in by_name
    # Dotted operationId is sanitised to a valid MCP tool name.
    assert "get_thing" in by_name
    list_things = by_name["listThings"]
    assert list_things.input_schema["type"] == "object"
    assert "limit" in list_things.input_schema["properties"]
    get_thing = by_name["get_thing"]
    assert "id" in get_thing.input_schema["required"]


async def test_openapi_to_tools_operations_filter() -> None:
    spec = {
        "paths": {
            "/a": {"get": {"operationId": "opA"}},
            "/b": {"get": {"operationId": "opB"}},
        }
    }
    tools = await openapi_to_tools(spec=spec, operations=["opA"])
    assert [t.name for t in tools] == ["opA"]


def test_auth_config_from_openapi_picks_bearer() -> None:
    spec = {
        "components": {
            "securitySchemes": {"s": {"type": "http", "scheme": "bearer"}}
        }
    }
    cfg = AuthConfig.from_openapi(spec)
    assert cfg.type == "bearer"
