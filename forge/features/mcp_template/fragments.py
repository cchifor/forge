"""MCP-template fragments — first-party MCP integration server scaffolding.

The MCP-server template (build_server, the plugin contract, ToolDef, and
the OpenAPI → tools generator) is vendored into the generated project
under ``src/app/mcp/_template/`` and imports only the official ``mcp``
library + starlette + httpx (and optional opentelemetry / prometheus /
PyYAML) — no private SDKs. ``tenant_id`` is optional, the
``transport=="internal"`` manifest enforcement is dropped, and the dead
OAuth / credentials-vault modules are not vendored.

Fragment names use the ``mcp_template_`` prefix to avoid colliding with
the existing ``mcp_server`` / ``mcp_ui`` fragments under
``forge.features.platform`` (which scaffold the consumer side: a tool
registry + approval UI for invoking *external* MCP servers).
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="mcp_template_server",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("mcp_template_server", "python"),
                    # Vendored template — only the official mcp library is
                    # a real extra; starlette + httpx ship in the base.
                    dependencies=("mcp>=1.0.0",),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="mcp_template_openapi_tools",
            depends_on=("mcp_template_server",),
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("mcp_template_openapi_tools", "python"),
                    # The vendored openapi generator uses PyYAML (a base
                    # dependency) — no extra dep needed.
                ),
            },
        )
    )
