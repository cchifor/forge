"""``mcp_template.*`` — first-party MCP integration server options.

Distinct from ``platform.mcp`` (which scaffolds the *consumer* side — a
backend tool registry + approval UI for invoking external MCP servers).
``mcp_template.*`` hosts a first-party MCP server inside this service
via the ``weld-mcp-template`` SDK.
"""

from __future__ import annotations

from forge.api import ForgeAPI
from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
)


def register_all(api: ForgeAPI) -> None:
    api.add_option(
        Option(
            path="mcp_template.server",
            type=OptionType.BOOL,
            default=False,
            summary="Host a first-party MCP server inside this service (weld-mcp-template).",
            description="""\
Scaffolds ``src/app/mcp/`` with a sample :class:`IntegrationPlugin`,
``build_server()`` factory, and an ASGI mount on ``/mcp``. Use for
services that expose first-party SaaS integrations to MCP clients
(the platform gateway connects to this endpoint).

BACKENDS: python
DEPENDENCY: weld-mcp-template, mcp""",
            category=FeatureCategory.PLATFORM,
            stability="beta",
            enables={True: ("mcp_template_server",)},
        )
    )

    api.add_option(
        Option(
            path="mcp_template.openapi_to_tools",
            type=OptionType.BOOL,
            default=False,
            summary="Generate MCP tool definitions from the service's OpenAPI spec.",
            description="""\
Adds a build step (``mise run mcp:codegen``) that runs
:func:`weld.mcp_template.openapi_to_tools` against the service's own
OpenAPI spec, producing a ``tools.generated.py`` consumed by the
default plugin. Useful when the service already exposes a REST surface
that should be 1:1 visible to MCP clients.

REQUIRES: ``mcp_template.server`` = true
BACKENDS: python""",
            category=FeatureCategory.PLATFORM,
            stability="experimental",
            enables={True: ("mcp_template_openapi_tools",)},
        )
    )
