"""Platform-ops fragments — operator-facing tooling.

Admin UI (``admin_panel``), outbound webhooks (``webhooks``), CLI
extensions (``cli_commands``), AI-agent docs (``agents_md``) and the
MCP (Model Context Protocol) server + per-frontend UI components.
``mcp_ui*`` fragments are project-scoped and copy frontend-specific
UI helpers into the active frontend tree.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="admin_panel",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="admin_panel/python",
                dependencies=("sqladmin>=0.20.0", "itsdangerous>=2.2.0"),
                env_vars=(("ADMIN_PANEL_MODE", "dev"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="webhooks",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="webhooks/python",
                dependencies=("httpx>=0.28.0",),
            ),
            BackendLanguage.NODE: FragmentImplSpec(fragment_dir="webhooks/node"),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="webhooks/rust",
                dependencies=("hmac@0.12", "sha2@0.10"),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="cli_commands",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="cli_commands/python"),
        },
    )
)


# Project-scoped: AGENTS.md is the same file for every backend, so we
# share a single FragmentImplSpec across all three.
_AGENTS_MD_IMPL = FragmentImplSpec(fragment_dir="agents_md/all", scope="project")
register_fragment(
    Fragment(
        name="agents_md",
        implementations={
            BackendLanguage.PYTHON: _AGENTS_MD_IMPL,
            BackendLanguage.NODE: _AGENTS_MD_IMPL,
            BackendLanguage.RUST: _AGENTS_MD_IMPL,
        },
    )
)


register_fragment(
    Fragment(
        name="mcp_server",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="mcp_server/python",
                env_vars=(("MCP_CONFIG_PATH", "mcp.config.json"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="mcp_ui",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="mcp_ui",
                scope="project",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="mcp_ui_svelte",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="mcp_ui_svelte",
                scope="project",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="mcp_ui_flutter",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="mcp_ui_flutter",
                scope="project",
            ),
        },
    )
)
