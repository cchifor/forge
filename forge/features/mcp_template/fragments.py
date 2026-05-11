"""MCP-template fragments — first-party MCP integration server scaffolding.

Fragment names use the ``mcp_template_`` prefix to avoid colliding with
the existing ``mcp_server`` / ``mcp_ui`` fragments under
``forge.features.platform`` (which scaffold the consumer side: a tool
registry + approval UI for invoking *external* MCP servers).
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


register_fragment(
    Fragment(
        name="mcp_template_server",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("mcp_template_server", "python"),
                dependencies=("weld-mcp-template", "mcp>=1.0.0"),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="mcp_template_openapi_tools",
        depends_on=("mcp_template_server",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("mcp_template_openapi_tools", "python"),
                dependencies=("weld-mcp-template[openapi]",),
            ),
        },
    )
)
