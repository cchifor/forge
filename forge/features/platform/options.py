"""``platform.*`` options — admin UI, webhooks, CLI extensions, MCP, AGENTS.md."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="platform.admin",
        type=OptionType.BOOL,
        default=False,
        summary="SQLAdmin UI at /admin -- tenant-scoped ModelViews.",
        description="""\
A browser-facing admin UI mounted at /admin, built on SQLAdmin. It
auto-registers ModelViews for whichever tables the enabled options
have shipped — items, audit_logs, conversations, messages, webhooks
— and skips any model whose Python import fails.

BACKENDS: python
ENDPOINTS: /admin (HTML UI)
REQUIRES: ADMIN_PANEL_MODE=disabled|dev|all (env var); sqladmin +
itsdangerous.""",
        category=FeatureCategory.PLATFORM,
        stability="beta",
        enables={True: ("admin_panel",)},
    )
)


register_option(
    Option(
        path="platform.webhooks",
        type=OptionType.BOOL,
        default=False,
        summary="Outbound registry + HMAC-signed delivery (ts + nonce + body).",
        description="""\
A registry + HMAC-SHA256 signed outbound delivery pipeline. Clients
POST to /api/v1/webhooks to register a target URL; your code calls
``fireEvent`` to deliver a signed JSON payload. Receiver verifies the
same way across all three backends — the signature header format is
identical.

BACKENDS: python, node, rust
ENDPOINTS: /api/v1/webhooks (CRUD + /{id}/test fire)""",
        category=FeatureCategory.PLATFORM,
        stability="beta",
        enables={True: ("webhooks",)},
    )
)


register_option(
    Option(
        path="platform.cli_extensions",
        type=OptionType.BOOL,
        default=False,
        summary="Typer subcommands -- `app info`, `app tools`, `app rag`.",
        description="""\
Extends the generated service's ``app`` typer CLI with operational
subcommands: ``app info show`` (environment dump), ``app tools
list``/``invoke`` (exercise registered agent tools), ``app rag
ingest`` (ingest a local file into the knowledge base). Each subcommand
degrades gracefully — if its prerequisite option isn't enabled, it
prints a hint and exits non-zero.

BACKENDS: python
ENDPOINTS: none — CLI surface only.""",
        category=FeatureCategory.PLATFORM,
        stability="beta",
        enables={True: ("cli_commands",)},
    )
)


register_option(
    Option(
        path="platform.mcp",
        type=OptionType.BOOL,
        default=False,
        summary="Model Context Protocol router + UI scaffolds for tool discovery and approval.",
        description="""\
Scaffolds a backend ``/mcp/tools`` + ``/mcp/invoke`` router (Python,
FastAPI) plus Vue ToolRegistry + ApprovalDialog components. Config
lives at project-root ``mcp.config.json`` (schema at
``forge/templates/_shared/mcp/mcp_config_schema.json``). Real MCP
subprocess spawning and tool-call proxying land in 1.0.0a3 — this alpha
ships the stable endpoints + UI surface so integrators can start
wiring today.

BACKENDS: python
FRONTENDS: vue (svelte + flutter in 1.0.0a3)
DOCS: docs/mcp.md.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        enables={True: ("mcp_server", "mcp_ui")},
    )
)


register_option(
    Option(
        path="platform.agents_md",
        type=OptionType.BOOL,
        default=True,
        summary="Drops AGENTS.md + CLAUDE.md for AI-coding-agent orientation.",
        description="""\
Drops AGENTS.md + CLAUDE.md at the project root so AI coding agents
(Claude Code, Cursor, Copilot workspaces) have a structured
orientation document before they touch generated code. Covers the
option stamp, backend layout, test commands, and the house
conventions so agents ship PRs that match the project's style on the
first try.

BACKENDS: python, node, rust (same content, project-scoped)""",
        category=FeatureCategory.PLATFORM,
        enables={True: ("agents_md",)},
    )
)
