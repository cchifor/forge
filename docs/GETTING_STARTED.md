# Getting started with forge

A 10-minute tour from install to a running full-stack project.

## Install

```bash
# Requires Python 3.13+.
uv tool install forge-cli   # or: pip install forge-cli (the installed command is `forge`)

# Sanity check.
forge --version
forge --doctor           # Verify Python / Node / Rust / Docker on PATH
```

## Interactive mode (the 5-minute path)

```bash
forge
```

Answer the prompts. Pick a backend (Python, Node, or Rust), a frontend (Vue, Svelte, Flutter, or none), a project name, and off you go. forge writes the project under the current directory and optionally runs `docker compose up`.

## Drop a new service into the platform monorepo

Since 1.2.0-alpha.1, the Python service template is wired to drop straight into `platform/services/`. The generated service consumes the platform's [10 weld-* SDKs](https://github.com/your-org/platform/blob/main/sdks/README.md) via monorepo path deps and inherits the same Dockerfile, docker-compose fragment, and Traefik routing conventions as every existing platform service.

```bash
cd /path/to/platform
forge --template python-service \
      --set project_name=widget \
      --set service_port=5042 \
      --set sdk_consumption=monorepo \
      --output services/widget
```

What you get out of the box:

- `pyproject.toml` declaring the default weld-* base (`auth, core, fastapi, observability, http-client, events`) with `[tool.uv.sources]` pointing at `../../sdks/weld-*`.
- Multi-stage `Dockerfile` that copies weld-* source from the `sdks` build context, builds wheels, and strips `[tool.uv.sources]` so the runtime image resolves from `/wheels`.
- `docker-compose.fragment.yaml` merged into the platform compose file: separate `widget-migrate` job + `widget` runtime service, Traefik path-rewrite for `/api/widget`, `depends_on` on postgres-healthy + keycloak-healthy.
- `src/app/` skeleton already importing from `weld.core.persistence.*`, `weld.fastapi.security.*`, `weld.fastapi.api.errors.Error`, `weld.core.discovery`. No `src/service/` shim.

Then enable any of the opt-in feature modules with `--set`:

```bash
--set events.bus=postgres_notify   # CloudEvents bus + transactional outbox
--set streaming.sse=true           # /api/v1/stream SSE endpoint
--set connectors.enabled=true      # weld-connectors registry
--set connectors.backends='["http","sql"]'
--set airlock.client=true          # Airlock sandbox-orchestrator client
--set mcp_template.server=true     # First-party MCP integration server
```

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
