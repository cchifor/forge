<div align="center">

# forge

*The single-command, polyglot full-stack generator for production services, agent platforms, and RAG apps.*

[![version](https://img.shields.io/badge/version-0.1.0-blue?style=flat-square)](https://github.com/cchifor/forge)
[![python](https://img.shields.io/badge/python-%3E%3D3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macos-lightgrey?style=flat-square)](https://github.com/cchifor/forge)
[![tests](https://img.shields.io/badge/tests-316%20passed-brightgreen?style=flat-square)](https://github.com/cchifor/forge/actions)
[![coverage](https://img.shields.io/badge/coverage-92%25-brightgreen?style=flat-square)](https://github.com/cchifor/forge/actions)
[![backends](https://img.shields.io/badge/backends-3-informational?style=flat-square)](docs/FEATURES.md)
[![frontends](https://img.shields.io/badge/frontends-3-informational?style=flat-square)](docs/FEATURES.md)
[![features](https://img.shields.io/badge/features-27-informational?style=flat-square)](docs/FEATURES.md)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](CONTRIBUTING.md)

</div>

`forge` is a CLI that scaffolds production-ready full-stack platforms from a single YAML (or a single interactive run). Where [create-next-app](https://nextjs.org/docs/app/api-reference/cli/create-next-app) and [cookiecutter-fastapi](https://github.com/tiangolo/full-stack-fastapi-template) give you one frontend and one backend, forge combines three backends ([FastAPI](https://fastapi.tiangolo.com/), [Fastify](https://fastify.dev/), [Axum](https://github.com/tokio-rs/axum)), three frontends ([Vue 3](https://vuejs.org/), [Svelte 5](https://svelte.dev/), [Flutter](https://flutter.dev/)), enterprise auth ([Keycloak](https://www.keycloak.org/) + [Gatekeeper](https://gatekeeper.readthedocs.io/) + [Traefik](https://traefik.io/)) and a pluggable 27-feature registry — then wires them behind one reverse proxy with Docker Compose. It's designed to be driven by humans in a terminal **and** by autonomous AI agents through a headless, stdin-pipeable, JSON-first CLI, so CI pipelines, Claude Code, or Copilot workspaces can generate the same project you would.

---

## Visuals

> The four slots below are placeholders awaiting contributor PRs. Each link notes the intended asset and tag contributors should produce.

![Interactive run (asciinema)](docs/assets/forge-interactive.svg)
*Terminal cast of the interactive generator asking for backend, frontend, entities, and producing a runnable stack. Capture via `asciinema rec` → `svg-term`.*

![Architecture diagram](docs/assets/architecture.svg)
*Mermaid diagram: browser → Traefik → (Vue \| Svelte \| Flutter) + (FastAPI \| Fastify \| Axum) + Postgres + Redis + Keycloak/Gatekeeper.*

![Generated Vue app with agentic chat](docs/assets/generated-vue.png)
*Screenshot of a generated Vue + Keycloak app displaying the AG-UI chat panel streaming from the `/ws/agent` endpoint.*

![forge --list-features output](docs/assets/feature-list.png)
*Screenshot of `forge --list-features` showing the 27-feature catalogue, stability tiers, and per-backend coverage.*

---

## Features

Enable any feature below at generation time with `--enable-feature KEY` (repeatable) or declare it inside your YAML config. See [Usage Examples](#usage-examples).

| Category | Feature / Capability | Status | Backends | What you get |
|---|---|---|---|---|
| **Foundation** | Polyglot backends | stable | python, node, rust | [FastAPI](https://fastapi.tiangolo.com/) / [Fastify](https://fastify.dev/) / [Axum](https://github.com/tokio-rs/axum) with matching ORM + migrations + lint/test toolchain. |
| **Foundation** | Frontends | stable | vue, svelte, flutter | [Vue 3](https://vuejs.org/) + Vite + TanStack Query, [SvelteKit](https://svelte.dev/) + runes, [Flutter](https://flutter.dev/) (web) + Riverpod. All ship an [AG-UI](https://github.com/cchifor/ag-ui) chat panel. |
| **Foundation** | Docker-compose + Traefik | stable | all | Generated `docker-compose.yml` with [Traefik](https://traefik.io/) routing `/api/{backend}` per-service. Multi-backend + per-service migrations included. |
| **Foundation** | Enterprise auth | stable | all | [Keycloak](https://www.keycloak.org/) realm JSON validated at generate-time, [Gatekeeper](https://gatekeeper.readthedocs.io/) OIDC ForwardAuth, Traefik forward-auth middleware. |
| **Foundation** | `forge.toml` stamping | stable | all | Generated project records forge version + template paths + feature set; machine-readable for future `forge update`. |
| **Middleware (Tier 1)** | `correlation_id` | stable, always-on | python | X-Request-ID ingress + ContextVar + response echo. |
| **Middleware (Tier 1)** | `rate_limit` | stable, on by default | python, node, rust | Token-bucket limiter: in-memory (Py), [`@fastify/rate-limit`](https://github.com/fastify/fastify-rate-limit) (Node), Axum tower middleware (Rust). |
| **Middleware (Tier 1)** | `security_headers` | stable, on by default | python, node, rust | CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, HSTS on HTTPS responses. |
| **Middleware (Tier 1)** | `pii_redaction` | stable, on by default | python | stdlib logging filter that scrubs emails, bearer tokens, API keys before handlers run. |
| **Ops (Tier 2)** | `observability` | stable | python, node, rust | [Logfire](https://logfire.pydantic.dev/) auto-instrumentation (Py) / [`@opentelemetry/sdk-node`](https://opentelemetry.io/docs/languages/js/) (Node) / OTLP gRPC via [`tracing-opentelemetry`](https://crates.io/crates/tracing-opentelemetry) (Rust). |
| **Ops (Tier 2)** | `response_cache` | beta | python, node | `fastapi-cache2` + Redis (Py) / `@fastify/caching` (Node). |
| **Ops (Tier 2)** | `background_tasks` | beta | python, node, rust | [Taskiq](https://taskiq-python.github.io/) broker (Py) / [BullMQ](https://docs.bullmq.io/) + ioredis (Node) / [Apalis](https://github.com/geofmureithi/apalis) + Redis (Rust). |
| **Ops (Tier 2)** | `enhanced_health` | beta | python, node, rust | `/api/v1/health/deep` aggregates Postgres + Redis + Keycloak readiness. |
| **Agent (Tier 3)** | `conversation_persistence` | beta | python | SQLAlchemy `Conversation`/`Message`/`ToolCall` + Alembic migration. |
| **Agent (Tier 3)** | `agent_tools` | experimental | python | Tool base class + process-wide registry + pre-baked `current_datetime` + `web_search` + `/api/v1/tools` endpoint. |
| **Agent (Tier 3)** | `agent_streaming` | experimental | python | `/api/v1/ws/agent` WebSocket with typed event protocol (`text_delta`, `tool_call`, `tool_result`, `agent_status`, …) and a runner-dispatch module. |
| **Agent (Tier 3)** | `agent` | experimental | python | [pydantic-ai](https://ai.pydantic.dev/) LLM loop — Anthropic / OpenAI / Google / OpenRouter. Real per-delta streaming via `agent.iter()`; graceful fallback if event classes change. |
| **Agent (Tier 3)** | `file_upload` | beta | python | `/api/v1/chat-files` multipart endpoint + `ChatFile` model + local storage with path-traversal guard. |
| **RAG (Tier 4)** | `rag_pipeline` | experimental | python | OpenAI embeddings + [pgvector](https://github.com/pgvector/pgvector) + HNSW index + recursive chunker + `/api/v1/rag/{ingest,ingest-pdf,search}` + auto-registered `rag_search` tool. |
| **RAG (Tier 4)** | `rag_postgresql` | experimental | python | Plain-PostgreSQL backend — no `vector` extension required. JSONB embeddings + Python-side cosine. |
| **RAG (Tier 4)** | `rag_qdrant` | experimental | python | [Qdrant](https://qdrant.tech/) async client, HNSW + COSINE. |
| **RAG (Tier 4)** | `rag_chroma` | experimental | python | [Chroma](https://www.trychroma.com/) async HTTP client; auto-creates collection. |
| **RAG (Tier 4)** | `rag_milvus` | experimental | python | [Milvus](https://milvus.io/) / Zilliz Cloud via `pymilvus.AsyncMilvusClient`. |
| **RAG (Tier 4)** | `rag_weaviate` | experimental | python | [Weaviate](https://weaviate.io/) v4 async client; BYO vectors. |
| **RAG (Tier 4)** | `rag_pinecone` | experimental | python | [Pinecone](https://www.pinecone.io/) managed service; namespace-per-tenant isolation. |
| **RAG (Tier 4)** | `rag_reranking` | experimental | python | Cohere `rerank-v3.5` (default) + local sentence-transformers cross-encoder fallback. |
| **RAG (Tier 4)** | `rag_embeddings_voyage` | experimental | python | [Voyage AI](https://www.voyageai.com/) embeddings drop-in replacement. |
| **RAG (Tier 4)** | `rag_sync_tasks` | experimental | python | Taskiq tasks for off-thread RAG ingestion. |
| **DX (Tier 5)** | `admin_panel` | beta | python | [SQLAdmin](https://aminalaee.dev/sqladmin/) UI at `/admin`, env-gated (`dev`/`all`/`disabled`). |
| **DX (Tier 5)** | `webhooks` | beta | python, node, rust | CRUD registry + HMAC-SHA256 signed outbound delivery + `/test` endpoint. |
| **DX (Tier 5)** | `cli_commands` | beta | python | Typer subcommands: `app info`, `app tools`, `app rag ingest`. |
| **DX (Tier 5)** | `agents_md` | stable, on by default | any (project-scoped) | Drops `AGENTS.md` + `CLAUDE.md` at the project root so AI coding agents orient themselves before editing. |

---

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** (latest) — forge ships as a uv tool. The installer bootstraps it if missing.
- **Python ≥ 3.11** — only if you want to regenerate or contribute. End users never need Python directly.
- **[Git](https://git-scm.com/)** — forge initialises a git repo in every generated project.
- **[Docker](https://www.docker.com/) + Compose v2** — required to run the generated stack.
- **Conditional toolchains for the backend / frontend you pick:** [Node.js](https://nodejs.org/) ≥ 22, [Rust](https://rustup.rs/) stable, [Flutter](https://docs.flutter.dev/get-started/install) ≥ 3.19.

forge is tested on **Windows 11 (Git Bash), Ubuntu 22.04+, and macOS 14+**, against Python 3.11 / 3.12 / 3.13.

---

## Quick Start

Three commands. Zero assumptions about prior toolchain install — the installer handles `uv` for you.

1. **Install forge.** The installer detects your OS, installs `uv` if missing, then drops `forge` on your PATH.
   ```bash forge-install
   curl -fsSL https://raw.githubusercontent.com/cchifor/forge/main/install | bash
   ```

2. **Generate a project.** Run `forge` with no arguments for the interactive prompt. (Skip ahead to [Usage Examples](#usage-examples) for the headless YAML and AI-agent pathway.)
   ```bash forge-quick-generate
   forge
   ```

3. **Launch the stack.** `cd` into the output directory and bring everything up.
   ```bash forge-docker-up
   cd my_platform && docker compose up --build
   ```

Your services now answer on `http://app.localhost`, Keycloak on `http://localhost:18080`, and the [Traefik](https://traefik.io/) dashboard on `http://localhost:19090`. Everything is wired.

---

## Usage Examples

### Interactive walk-through

```text forge-interactive-transcript
$ forge

  +===================================+
  |             forge                  |
  |      Project Generator             |
  +===================================+

  ? Project name: My Platform
  ? Description: A full-stack application

  -- Backend 1 --
  ? Backend name: api
  ? Backend language: Python (FastAPI)
  ? Backend server port: 5000
  ? Python (FastAPI) version: 3.13
  ? CRUD entities to generate (comma-separated, e.g. items, orders): items
  ? Add another backend? No

  -- Frontend --
  ? Frontend framework: Vue 3
  ? Author name: Ada Lovelace
  ? Package manager: pnpm
  ? Frontend server port: 5173
  ? Enable Keycloak authentication? Yes
  ? Enable AI chat panel? No
  ? Default color scheme: blue

  -- Keycloak --
  ? Keycloak host port: 18080
  ? Keycloak realm: app
  ? Keycloak client ID: my-platform

  -- Summary --
  Project:    My Platform
  Backend:    Python 3.13 on port 5000
  Frontend:   Vue on port 5173
  Features:   items
  Auth:       Keycloak
  Keycloak:   port 18080

  ? Proceed with generation? Yes
  Project generated at: /home/ada/my_platform
```

### Headless generation from a YAML config

Write your stack as a file, then run one command. This is the path most teams will standardise on for CI pipelines.

```yaml forge-project-config
# stack.yaml
project_name: my-shop
description: An e-commerce platform

backend:
  language: python
  server_port: 5000
  features: products, orders, customers
  python_version: "3.13"

frontend:
  framework: vue
  package_manager: pnpm
  include_auth: true

keycloak:
  port: 18080
  realm: my-shop
  client_id: my-shop

features:
  observability:
    enabled: true
  enhanced_health:
    enabled: true
  webhooks:
    enabled: true
```

```bash forge-headless-yaml
forge --config stack.yaml --yes --no-docker --json
```

Expected output on stdout (progress goes to stderr):

```json forge-json-success
{
  "project_root": "/home/ada/my-shop",
  "backends": [
    {"name": "backend", "dir": "/home/ada/my-shop/backend", "language": "python", "port": 5000}
  ],
  "backend_dir": "/home/ada/my-shop/backend",
  "frontend_dir": "/home/ada/my-shop/frontend",
  "framework": "vue",
  "features": ["products", "orders", "customers"]
}
```

### AI-agent / stdin pathway

forge's CLI is designed so an autonomous coding agent can generate a project without touching the filesystem first. Pipe a JSON or YAML spec straight in and parse the JSON envelope that comes back.

```bash forge-stdin-pipe-ai-agent
echo '{
  "project_name": "api-gateway",
  "backend": {"language": "rust", "server_port": 5001},
  "frontend": {"framework": "none"},
  "features": {"webhooks": {"enabled": true}, "observability": {"enabled": true}}
}' | forge --config - --yes --no-docker --json
```

Exit codes are strict and machine-friendly:

| Code | Meaning |
|---|---|
| `0` | Project generated successfully. stdout contains the success envelope. |
| `1` | User aborted at a prompt (only reachable without `--yes`). |
| `2` | Config, validation, or generation error. stdout is the error envelope; stderr has the human message. |

On failure you'll see:

```json forge-json-error
{"error": "Feature 'agent_streaming' requires 'conversation_persistence' but 'conversation_persistence' is not enabled."}
```

### Enabling optional features

Stack your flags. The `capability_resolver` validates transitive dependencies (e.g. `agent` implies `agent_streaming` + `agent_tools` + `conversation_persistence`) and refuses to proceed with a clear error instead of half-generating.

```bash forge-feature-flags
forge --config stack.yaml --yes --no-docker \
  --enable-feature conversation_persistence \
  --enable-feature agent_streaming \
  --enable-feature agent_tools \
  --enable-feature agent \
  --enable-feature rag_pipeline \
  --enable-feature observability
```

### Inspect the full feature registry

```bash forge-list-features-cmd
forge --list-features
```

```text forge-list-features
KEY                      STABILITY    DEFAULT  BACKENDS
admin_panel              beta         off      python
agent                    experimental off      python
agent_streaming          experimental off      python
agent_tools              experimental off      python
agents_md                stable       on       node,python,rust
background_tasks         beta         off      node,python,rust
cli_commands             beta         off      python
conversation_persistence beta         off      python
correlation_id           stable       always-on python
enhanced_health          beta         off      node,python,rust
file_upload              beta         off      python
observability            stable       off      node,python,rust
pii_redaction            stable       on       python
rag_chroma               experimental off      python
rag_embeddings_voyage    experimental off      python
rag_milvus               experimental off      python
rag_pinecone             experimental off      python
rag_pipeline             experimental off      python
rag_postgresql           experimental off      python
rag_qdrant               experimental off      python
rag_reranking            experimental off      python
rag_sync_tasks           experimental off      python
rag_weaviate             experimental off      python
rate_limit               stable       on       node,python,rust
response_cache           beta         off      node,python
security_headers         stable       on       node,python,rust
webhooks                 beta         off      node,python,rust
```

### Polyglot stack (Python + Rust behind one gateway)

```yaml forge-polyglot-config
# polyglot.yaml — Python and Rust backends fronted by a Vue SPA + Keycloak.
project_name: Multi Stack

backends:
  - name: api-py
    language: python
    features: ["items"]
    server_port: 5010
  - name: api-rs
    language: rust
    features: ["orders"]
    server_port: 5012

frontend:
  framework: vue
  include_auth: true
  package_manager: pnpm

keycloak:
  port: 18080
  realm: app
  client_id: multi-stack

features:
  observability:
    enabled: true
  enhanced_health:
    enabled: true
  webhooks:
    enabled: true
```

Traefik routes `/api/api-py/...` to FastAPI and `/api/api-rs/...` to Axum, each with its own Postgres database, its own migration container, and the same Keycloak realm enforcing auth.

### What a generated project looks like

```text forge-generated-tree
my_platform/
├── forge.toml                 # forge version, template paths, enabled features
├── docker-compose.yml         # Traefik + services + Postgres + optional Keycloak
├── init-db.sh                 # Creates per-service + Keycloak databases
├── services/
│   └── api/                   # FastAPI / Fastify / Axum app, its own Dockerfile + tests
├── apps/
│   └── frontend/              # Vue / Svelte / Flutter SPA (or absent for frontend=none)
├── infra/                     # Only present with --include-auth
│   ├── keycloak-realm.json    # Pre-configured realm, validated at generate-time
│   ├── keycloak/              # Keycloak Dockerfile + themes
│   └── gatekeeper/            # OIDC ForwardAuth proxy
├── tests/
│   └── e2e/                   # Playwright suite (8 tests per feature + 4 auth flows)
├── AGENTS.md                  # Orientation for AI coding agents
├── CLAUDE.md                  # Orientation for Claude Code / Cursor users
└── README.md
```

### Regenerating later (including new features)

forge stamps every generated project with `forge.toml` recording the forge version, per-template paths, and the enabled feature set. Today the workflow is:

1. Update your `stack.yaml` (add features, change backends, adjust entities).
2. Regenerate into a scratch directory: `forge --config stack.yaml --yes --no-docker --output-dir ./tmp`.
3. Diff against your existing project and cherry-pick the changes.

A first-class `forge update` subcommand that does this merge automatically is on the [Roadmap](#roadmap).

Looking for more sophisticated examples? See [`examples/`](examples/) for curated sample configs and [`docs/FEATURES.md`](docs/FEATURES.md) for the deep feature catalogue.

---

## Support

- **Issue tracker:** [github.com/cchifor/forge/issues](https://github.com/cchifor/forge/issues) — bug reports, feature requests, roadmap suggestions.
- **Discussions:** [github.com/cchifor/forge/discussions](https://github.com/cchifor/forge/discussions) — questions, show-and-tell, architectural back-and-forth.
- **Changelog:** release-to-release deltas live in [`CHANGELOG.md`](CHANGELOG.md).
- **Security reports:** please email the maintainer before opening a public issue.

---

## Roadmap

| Horizon | Item | Why it matters |
|---|---|---|
| **Next up** | `forge update` subcommand | Apply a changed `stack.yaml` to an existing project as a clean diff, no scratch directory required. |
| **Next up** | `security_ratelimit_strict` composite preset | One flag that bundles `rate_limit` + `security_headers` + tightened CORS for regulated deployments. |
| **Next up** | Go backend (`go-service-template`) | Fourth backend language — Echo + pgx + sqlc pattern mirrors the other three. |
| **Next up** | React 19 frontend | TanStack Start + React Query + Zod; lives alongside Vue / Svelte / Flutter. |
| **Considered** | `cli_commands` ports to Node + Rust | npm scripts cover much of Node's surface; clap layered on `src/bin/migrate.rs` for Rust. |
| **Considered** | `response_cache/rust` | `moka` + tower layer once a canonical idiom emerges. |
| **Considered** | Alternative embeddings providers | Cohere, local `sentence-transformers`; same pattern as `rag_embeddings_voyage`. |
| **Considered** | Kubernetes manifests | Helm chart or Kustomize bundle generated alongside `docker-compose.yml`. |
| **Considered** | Third-party fragment plugin API | Let external crates / packages register `FeatureSpec` entries so downstream teams can ship their own opt-in features. |

File or upvote items on the [issue tracker](https://github.com/cchifor/forge/issues).

---

## Contributing

Contributions are welcome — bug fixes, new features, new backends, new frontends, translations, docs polish. Start here:

```bash forge-contributor-setup
git clone https://github.com/cchifor/forge.git
cd forge
uv sync --all-extras --dev
uv run pre-commit install
```

Run the full pre-commit battery with:

```bash forge-make-check
make check      # ruff lint + ruff format --check + ty typecheck + pytest (~10s)
```

**What's required before a PR:**

- **Env vars:** none for unit tests. `OPENAI_API_KEY` + `ANTHROPIC_API_KEY` only if you're running the agent / RAG e2e manually. `POSTGRES_URL` only for the integration tests tagged `@pytest.mark.e2e`.
- **Linter / formatter:** `uv run ruff check forge/` and `uv run ruff format forge/` must both be clean.
- **Typechecker:** `uv run ty check forge/` (forge's typechecker of choice — not mypy).
- **Test runner:** `uv run pytest -m "not e2e"` must be green. Full e2e with `make e2e` (requires `uv`, `npm`, `cargo`, `git` on PATH). Generated projects ship a [Playwright](https://playwright.dev/) suite; forge itself has no browser tests.
- **Commit style:** [Conventional Commits](https://www.conventionalcommits.org/), imperative mood, subject line ≤ 50 chars, no AI co-author trailer. One logical change per PR.
- **Adding a feature fragment:** follow the author guide at [`docs/FEATURES.md`](docs/FEATURES.md) — pick a `key`, declare a `FragmentImplSpec`, drop files under `forge/templates/_fragments/<key>/<backend>/`, add a test row in `tests/test_features.py`, document the feature.

CI runs the full matrix — Ubuntu + Windows, Python 3.11 / 3.12 / 3.13 — on every push and PR. Nightly e2e runs on Ubuntu against Python 3.13.

---

## Authors and Acknowledgment

- **Creator & maintainer:** [Constantin Chifor](https://github.com/cchifor).
- **Built on the shoulders of:** [Copier](https://copier.readthedocs.io/), [Questionary](https://github.com/tmbo/questionary), [Jinja2](https://jinja.palletsprojects.com/), [uv](https://docs.astral.sh/uv/), [pydantic-ai](https://ai.pydantic.dev/), [FastAPI](https://fastapi.tiangolo.com/), [Fastify](https://fastify.dev/), [Axum](https://github.com/tokio-rs/axum), [SQLAlchemy](https://www.sqlalchemy.org/), [SQLx](https://github.com/launchbadge/sqlx), [Prisma](https://www.prisma.io/), [Tailwind CSS](https://tailwindcss.com/), [Vite](https://vite.dev/), [SvelteKit](https://svelte.dev/docs/kit/introduction), [Flutter](https://flutter.dev/), [Keycloak](https://www.keycloak.org/), [Traefik](https://traefik.io/), [Apalis](https://github.com/geofmureithi/apalis), [Taskiq](https://taskiq-python.github.io/), [BullMQ](https://docs.bullmq.io/).
- **Inspiration:** the agent + RAG feature set was ported from the [pydantic full-stack AI agent template](https://github.com/pydantic/full-stack-ai-agent-template). Their depth; forge's breadth.

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Project Status

Active development, weekly cadence.

- **Today:** 27 features registered, **316 tests** passing, **92 % coverage**, CI green on Linux + Windows against Python 3.11 / 3.12 / 3.13.
- **API stability:** 0.1.x is stabilising. Breaking changes are possible between minor releases; every such change is called out in [`CHANGELOG.md`](CHANGELOG.md).
- **Production-ready today:** the foundation, Tier 1 middleware, Tier 2 ops (observability / caching / background tasks / health), and most of Tier 5 DX.
- **Use with awareness:** Tier 3 agent platform and Tier 4 RAG are marked `experimental` — the interfaces work, but expect minor adjustments as pydantic-ai and the vector-store clients evolve.
- **v1.0 gates:** `forge update` subcommand, complete cargo-feature wiring for observability Rust, documented extension API for third-party fragments, a curated `examples/` directory.
