"""``platform.*``, ``object_store.*``, ``security.*`` — operator-facing surfaces.

Admin UI, outbound webhooks, CLI extensions, MCP scaffolds, AGENTS.md
docs, blob storage selection, and security headers / SBOM workflow.
Grouped together because they're all platform-level concerns that don't
fit cleanly into another namespace.
"""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

# --- platform.* -------------------------------------------------------------

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


# --- object_store.* ---------------------------------------------------------

register_option(
    Option(
        path="object_store.backend",
        type=OptionType.ENUM,
        default="none",
        options=("none", "s3", "local"),
        summary="Blob storage — AWS S3 / S3-compatible / local filesystem, behind ObjectStorePort.",
        description="""\
Selects which object-store implementation backs the ``ObjectStorePort``.
The ``s3`` adapter also handles MinIO / R2 / Wasabi (set S3_ENDPOINT_URL).
The ``local`` adapter writes under a filesystem root — dev / test only.

OPTIONS: none | s3 | local
BACKENDS: python
DEPENDENCY: aioboto3 (s3) | none (local)
ENV: AWS_REGION / S3_ENDPOINT_URL / OBJECT_STORE_ROOT""",
        category=FeatureCategory.PLATFORM,
        enables={
            "s3": ("object_store_port", "object_store_s3"),
            "local": ("object_store_port", "object_store_local"),
        },
    )
)


# --- security.* -------------------------------------------------------------

register_option(
    Option(
        path="security.csp",
        type=OptionType.BOOL,
        default=True,
        summary="Strict Content-Security-Policy + HSTS + X-Content-Type-Options via nginx.",
        description="""\
Drops ``infra/nginx-csp.conf`` with production-ready strict CSP (no
unsafe-inline, strict-dynamic, nonce-based script tags), HSTS, and
related defence-in-depth headers. ``include infra/nginx-csp.conf;`` from
any nginx server{} block.

BACKENDS: all (project-scoped)
DEV NOTE: relax the ``connect-src`` directive during local development
if your dev server streams from a non-default origin.""",
        category=FeatureCategory.PLATFORM,
        enables={True: ("security_csp",)},
    )
)


register_option(
    Option(
        path="security.sbom",
        type=OptionType.BOOL,
        default=False,
        summary="GitHub Actions workflow emitting a CycloneDX SBOM + pip-audit report.",
        description="""\
Adds ``.github/workflows/sbom.yml`` that generates a CycloneDX SBOM on
every push and runs pip-audit weekly. Artifacts are uploaded so SBOM
attestation and vulnerability disclosure happens as part of normal CI.

BACKENDS: python
DEPENDENCY: none runtime; CI installs cyclonedx-bom + pip-audit.""",
        category=FeatureCategory.OBSERVABILITY,
        enables={True: ("security_sbom",)},
    )
)
