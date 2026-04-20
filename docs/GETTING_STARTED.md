# Getting started with forge

A 10-minute tour from install to a running full-stack project.

## Install

```bash
# Requires Python 3.11+.
uv tool install forge   # or: pip install forge

# Sanity check.
forge --version
forge --doctor           # Verify Python / Node / Rust / Docker on PATH
```

## Interactive mode (the 5-minute path)

```bash
forge
```

Answer the prompts. Pick a backend (Python, Node, or Rust), a frontend (Vue, Svelte, Flutter, or none), a project name, and off you go. forge writes the project under the current directory and optionally runs `docker compose up`.

## Headless mode (the AI-agent / CI path)

Hand forge a YAML and let it run unattended:

```yaml
# forge.yaml
project_name: my_platform
output_dir: ./projects

backends:
  - name: api
    language: python
    python_version: "3.13"
    features: [items, orders]

frontend:
  framework: vue
  include_auth: true
  include_chat: true

options:
  reliability.connection_pool: true
  reliability.circuit_breaker: true
  observability.otel: true
  rag.backend: qdrant
  llm.provider: anthropic
  platform.mcp: true
```

```bash
forge --config forge.yaml --yes --no-docker
```

`--yes` skips confirmation, `--no-docker` skips the compose boot. For machine-readable output, add `--json`.

## What you get

```
my_platform/
├── forge.toml                # Project manifest + provenance
├── docker-compose.yml        # Traefik + Keycloak + Gatekeeper + backends
├── services/
│   └── api/                  # FastAPI service with rate_limit + tracing
│       ├── src/app/          # Domain / data / services / middleware
│       ├── pyproject.toml    # uv-managed deps, ruff + pytest configured
│       └── tests/            # Pytest + testcontainers for DB
├── apps/
│   └── web/                  # Vue 3 + Vite + Pinia + shadcn-vue
│       └── src/
│           ├── features/ai_chat/     # AG-UI chat panel streaming /agent/run
│           └── features/mcp/         # Tool registry + approval dialog
├── infra/
│   ├── gatekeeper/           # OIDC ForwardAuth (Keycloak → Traefik)
│   └── keycloak/             # Realm + themes
├── tests/e2e/                # Playwright tests
├── .github/workflows/ci.yml  # Backend + frontend lint + test matrix
├── .editorconfig
├── .gitignore
└── .pre-commit-config.yaml
```

## Explore the options

```bash
# Browse the 30+ options by category.
forge --list

# Deep-dive into one.
forge --describe rag.backend

# Preview a plan without writing anything.
forge --plan --config forge.yaml
```

## Incremental changes

```bash
# Add a new CRUD entity.
cd my_platform
forge --new-entity-name Order --new-entity-fields "name:string,qty:integer,status:enum:OrderStatus"

# Add a second backend to an existing project.
forge --add-backend-language rust --add-backend-name search

# Preview what --update would change.
forge --preview --config forge.yaml

# Re-apply fragments after a forge upgrade.
forge --update
```

## Re-apply safely

`forge --update` respects the zone semantics baked into each fragment:

- `generated` zones are overwritten — these are forge-owned regions
- `user` zones are preserved verbatim
- `merge` zones are three-way-merged against the baseline recorded in `forge.toml`; conflicts surface as `<file>.forge-merge` sidecars next to the originals

Every file forge writes carries a provenance record (origin + SHA-256) so the updater can distinguish user-modified content from stale fragment output.

## Codemods for older projects

Upgrading from a pre-1.0 forge? Run the umbrella migration:

```bash
forge --migrate
```

This invokes `migrate-ui-protocol` (retires hand-written `types.ts`), `migrate-entities` (suggests YAML skeletons), and `migrate-adapters` (scaffolds the ports/adapters split). Dry-run first with `--migrate --dry-run`.

## Agent-friendly invocation

Everything above works from an AI agent with no human in the loop:

```bash
# All flags machine-readable; stdout is pure JSON on success.
forge --config - --yes --no-docker --json <<EOF
{
  "project_name": "ephemeral_demo",
  "backends": [{"language": "python", "features": ["items"]}],
  "frontend": {"framework": "none"},
  "options": {"middleware.rate_limit": true}
}
EOF
```

`stdin` accepts JSON or YAML with `--config -`. On success, JSON mode writes one object to stdout (`{"project_root": "...", "backends": [...], ...}`); errors use `{"error": "..."}` with exit code 2.

## Next steps

- [ARCHITECTURE.md](ARCHITECTURE.md) — how forge itself is built
- [FEATURES.md](FEATURES.md) — the full option catalogue
- [plugin-development.md](plugin-development.md) — write your own plugins
- [RFC-001 Versioning](rfcs/RFC-001-versioning-branching.md) — release cadence
