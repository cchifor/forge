# Getting started with forge

A 10-minute tour from install to a running full-stack project.

## Install

```bash
# Requires Python 3.13+. forge is installed from source (GitHub-only — it is
# not published to PyPI). The installer bootstraps uv if it's missing.
curl -fsSL https://raw.githubusercontent.com/cchifor/forge/main/install | bash
# or, directly:  uv tool install git+https://github.com/cchifor/forge.git

# Sanity check.
forge --version
forge --doctor           # Verify Python / Node / Rust / Docker on PATH
```

## Interactive mode (the 5-minute path)

```bash
forge
```

Answer the prompts. Pick a backend (Python, Node, or Rust), a frontend (Vue, Svelte, Flutter, or none), a project name, and off you go. forge writes the project under the current directory and optionally runs `docker compose up`.

## Stand up a whole platform (`--platform`)

To scaffold a multi-service *system* instead of a single backend, pick a platform preset:

```bash
forge --platform microservices --project-name shop   # gateway + services + auth + event bus
forge --platform multitenant-saas --project-name app # tenant control plane + RLS-isolated app
```

Each preset assembles several services behind a shared Keycloak + Gatekeeper auth stack, with service-to-service trust (and per-tenant Postgres RLS for `multitenant-saas`). A preset is just the lowest-priority config layer, so your CLI flags and `--config` still win. See the [platform generator guide](platform-generator-guide.md) for the preset comparison, how S2S auth and multitenancy work, and **the dev-posture credentials you must rotate before deploying.**

## Add another backend to a project

forge projects are multi-backend monorepos. To add a service to an existing project, run from the project root:

```bash
cd my_platform
forge --add-backend-language python --add-backend-name billing
# …or node / rust:
forge --add-backend-language rust --add-backend-name search
```

forge re-renders the project with the new service wired in: a `services/<name>/` tree with its own Dockerfile, a `<name>-migrate` + `<name>` block in `docker-compose.yml`, and Traefik routing for `/api/<name>`. Each backend owns its own CRUD entities. Your existing services and edits are preserved by the three-zone merge (see [Re-apply safely](#re-apply-safely) below). Tune the new backend with the same `--set option.path=value` flags you'd use at generation time — browse them with `forge --list`.

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

- [architecture.md](architecture.md) — how forge itself is built
- [FEATURES.md](FEATURES.md) — the full option catalogue
- [plugin-development.md](plugin-development.md) — write your own plugins
- [RFC-001 Versioning](rfcs/RFC-001-versioning-branching.md) — release cadence
