<div align="center">

# forge

*Production-ready full-stack project generator with 3 backend languages, 3 frontend frameworks, and enterprise auth — from a single command.*

[Quick Start](#quick-start) · [Features](#features) · [Usage](#usage-examples) · [Architecture](docs/architecture.md) · [Add a backend](docs/adding-a-backend.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

[![version](https://img.shields.io/badge/version-0.1.0-blue?style=flat-square)](https://github.com/cchifor/forge) [![python](https://img.shields.io/badge/python-%3E%3D3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org) [![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE) [![platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macos-lightgrey?style=flat-square)](https://github.com/cchifor/forge) [![tests](https://img.shields.io/badge/tests-200%20passed-brightgreen?style=flat-square)](https://github.com/cchifor/forge)

**3 Backend Languages** *(Python/FastAPI, Node.js/Fastify, Rust/Axum — mix multiple per project)*
**3 Frontend Frameworks** *(Vue 3, Svelte 5, Flutter)*
**Agentic UI in every frontend** *(AG-UI streaming, tool calls, HITL, workspace + canvas panes)*
**Enterprise Auth** *(Keycloak, Gatekeeper OIDC, Traefik, Redis)*

<details>
<summary><b>Table of Contents</b></summary>

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Usage Examples](#usage-examples)
- [Architecture](#architecture)
- [Configuration Reference](#configuration-reference)
- [Support](#support)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Authors and Acknowledgment](#authors-and-acknowledgment)
- [License](#license)

</details>

</div>

---

## Features

| Category | What you get |
|----------|-------------|
| **Backend Choice** | Python ([FastAPI](https://fastapi.tiangolo.com) + SQLAlchemy + Alembic), Node.js ([Fastify 5](https://fastify.dev) + Prisma 6 + Zod), or Rust ([Axum 0.8](https://github.com/tokio-rs/axum) + SQLx + serde). **Multi-backend**: generate multiple backends per project, each with its own name, language, port, features, database, migration container, and Traefik route. |
| **Frontend Choice** | [Vue 3](https://vuejs.org) (Vite + TanStack Query + Zod), [Svelte 5](https://svelte.dev) (SvelteKit + TanStack Svelte Query + Zod), or [Flutter](https://flutter.dev) (web; Riverpod + GoRouter + freezed). All three ship a responsive dashboard with health checks and the same `--include-chat`, `--include-openapi`, `--default-color-scheme` toggles. |
| **Full CRUD Generation** | Name your entities (e.g., `products, orders`) and forge generates domain models, ORM models, repositories, services, REST endpoints, API clients, UI pages, schemas, MSW handlers, and tests — for every entity, in every layer. Multi-backend deployments transparently prefix per-feature API paths (`/api/{backend}/v1/{entity}`). |
| **Agentic UI** | All three frontends ship the same [AG-UI](https://github.com/ag-ui-protocol/ag-ui) chat: streaming text deltas, tool-call status, HITL prompts, model selector, approval-mode toggle. Workspace pane (file explorer, credential form, approval review, user-prompt review) and canvas pane (dynamic form, data table, report, code viewer, workflow diagram) ship via a registry pattern in each framework. Vue/Svelte additionally embed [MCP ext-apps](https://github.com/anthropics/ext-apps) sandboxed iframes; Flutter renders MCP activities natively. |
| **Production Docker** | Two-stage Dockerfiles for every backend and frontend. [Traefik v2.11](https://traefik.io) API gateway with per-backend path routing and auto-load-balancing. Dedicated migration containers for all languages (Alembic, Prisma Migrate, sqlx). nginx serves static files + SPA fallback only. PostgreSQL 16 with per-backend databases. |
| **Authentication** | Toggle `--include-auth` to get: [Keycloak 26](https://www.keycloak.org) identity provider with pre-configured realm, Gatekeeper OIDC ForwardAuth proxy (cookie-based — no keycloak-js on the frontend), [Traefik v2.11](https://traefik.io) edge router, Redis session cache, route guards, and sample users. Gatekeeper provides `/auth/login`, `/auth/userinfo`, `/logout` endpoints. The rendered `keycloak-realm.json` is JSON-validated before write so Jinja typos fail generation immediately. |
| **Multi-Tenancy** | All three backends enforce tenant isolation. Gatekeeper injects `X-Gatekeeper-User-Id`, `X-Gatekeeper-Tenant`, `X-Gatekeeper-Roles` headers. Python uses repository-level `_apply_scopes()`, Node.js/Rust use tenant middleware. Service-to-service calls propagate tenant context via headers. |
| **Headless / Agent Mode** | `--config`, `--json`, `--quiet`, `--verbose`, `--yes` flags for CI/CD and AI agents. Pipe JSON from stdin, get structured output on stdout, single-line `{"error": ...}` envelope + exit 2 on failure. Shell completion via `forge --completion bash|zsh|fish`. No TTY required. Works with `uvx` for zero-install execution. |
| **Reliability** | Generator failures surface as `GeneratorError` — git init, npm install, and Copier failures all propagate to JSON envelope or stderr+exit 2 instead of leaving a half-built project. Generated projects are stamped with `forge.toml` (forge version + per-language template paths) so existing scaffolds can be `copier update`d. |
| **Testing** | Pytest (Python), Vitest (Node.js), Cargo test (Rust), Vitest (Vue/Svelte), Flutter test. **Playwright E2E suite** per project (8 tests per feature + 4 auth) — run containerized via `docker compose --profile test run e2e`. Deterministic `data-test` / `data-testid` selectors on all UI components. Docker testcontainers for real PostgreSQL integration tests. |
| **Cross-Platform** | Windows (Git Bash), Linux, macOS. LF line endings enforced for Docker container scripts. CI matrix runs on Linux + Windows × Python 3.11/3.12/3.13. |

---

## Prerequisites

| Tool | Required? | Notes |
|------|-----------|-------|
| [uv](https://docs.astral.sh/uv/) | Yes | Installed automatically by the installer |
| [Git](https://git-scm.com) | Yes | For project generation and version control |
| [Docker](https://www.docker.com) | Recommended | Required to run the generated stack |
| [Node.js 22+](https://nodejs.org) | If generating Vue/Svelte | Not needed for Flutter or backend-only |
| [Flutter SDK](https://flutter.dev) | If generating Flutter | Not needed otherwise |
| [Rust toolchain](https://rustup.rs) | If generating Rust backend | Not needed otherwise |

---

## Quick Start

**Step 1 — Install forge globally:**

```bash
curl -fsSL https://raw.githubusercontent.com/cchifor/forge/main/install | bash
```

**Step 2 — Generate a full-stack project:**

```bash
forge
```

Follow the interactive prompts to pick your backend (Python, Node.js, or Rust), frontend (Vue, Svelte, Flutter, or None), and CRUD entities.

**Step 3 — Start the stack:**

```bash
cd my_platform/ && docker compose up --build
```

Your app is now running at `http://app.localhost` (Traefik gateway). API health: `http://app.localhost/api/backend/v1/health/live`. Traefik dashboard: `http://localhost:19090`.

**Step 4 — Run E2E tests (optional):**

```bash
docker compose --profile test run --rm e2e
```

Runs Playwright browser tests (8 per feature + 4 auth) in a containerized Chromium instance against the live stack.

---

## Usage Examples

### Interactive mode (human developers)

```bash
forge
```

The prompts guide you through backend language, frontend framework, entity names, auth, and feature toggles.

### Headless mode (AI agents, CI/CD, scripts)

**From a YAML config file:**

```bash
forge --config stack.yaml --yes --no-docker
```

```yaml
# stack.yaml — single backend
project_name: my-shop
description: An e-commerce platform

backend:
  language: python          # python | node | rust
  server_port: 5000
  features: products, orders, customers
  python_version: "3.13"    # python only
  # node_version: "22"      # node only
  # rust_edition: "2024"    # rust only

frontend:
  framework: vue            # vue | svelte | flutter | none
  package_manager: pnpm
  include_auth: true

keycloak:
  port: 18080
  realm: my-shop
  client_id: my-shop
```

**Multi-backend config file:**

```yaml
# microservices.yaml — multiple backends in one project
project_name: my-platform

backends:
  - name: users
    language: python
    server_port: 5000
    features: users, profiles
  - name: catalog
    language: rust
    server_port: 5001
    features: products, categories
  - name: notifications
    language: node
    server_port: 5002
    features: alerts

frontend:
  framework: vue
```

Each backend goes into `services/`, the frontend into `apps/`, and auth infrastructure into `infra/`. All services are accessed through `http://app.localhost`: `/api/users/v1/users` → users service, `/api/catalog/v1/products` → catalog service, etc.

**From CLI flags (no file needed):**

```bash
forge --project-name my-shop --backend-language rust --frontend vue \
  --features "products,orders" --include-auth --yes --no-docker
```

Expected output:
```
  Generating Rust backend ...
  Generating vue frontend ...
  Rendering docker-compose.yml ...
  Rendering keycloak-realm.json ...
  Copying gatekeeper ...
  Copying keycloak ...
  Generating Playwright e2e tests ...
  Rendering frontend Dockerfile ...
  Initializing git repository ...

  Project generated at: /path/to/my_shop
```

**Pipe JSON from stdin (AI agents):**

```bash
echo '{"project_name":"my-api","backend":{"language":"node"}}' \
  | forge --config - --yes --no-docker --json
```

Expected output (stdout only — all progress goes to stderr):
```json
{"project_root": "/path/to/my_api", "backends": [{"name": "backend", "dir": "/path/to/my_api/backend", "language": "node", "port": 5000}], "backend_dir": "/path/to/my_api/backend"}
```

On error, `--json` returns a structured error object (exit code 2):
```json
{"error": "Port 5000 is used by both frontend and backend."}
```

**Zero-install one-shot (no global install needed):**

```bash
uvx --from git+https://github.com/cchifor/forge.git forge \
  --config stack.yaml --yes --no-docker --json
```

### Run E2E tests (after docker compose up)

When a frontend is generated, forge creates a complete Playwright E2E testing suite in `tests/e2e/`. Tests run in a containerized Chromium browser against the live stack:

```bash
cd my_shop/
docker compose up --build -d
docker compose --profile test run --rm e2e
```

Expected output:
```
[global-setup] Authenticating user via http://app.localhost
[global-setup] ✓ user

  ✓  1 [chromium] › tests/auth.spec.ts › Authentication › unauthenticated user redirected to login
  ✓  2 [chromium] › tests/auth.spec.ts › Authentication › login with valid credentials
  ✓  3 [chromium] › tests/products.spec.ts › Products › List › loads and shows items
  ✓  4 [chromium] › tests/products.spec.ts › Products › Create › fills form and submits
  ✓  5 [chromium] › tests/products.spec.ts › Products › Detail › edit flow
  ✓  6 [chromium] › tests/products.spec.ts › Products › Detail › delete flow
  ...

  28 passed (30s)
```

Each feature generates 8 tests: list, search, empty state, create, validate, detail, edit, delete. Auth adds 4 more: unauthenticated redirect, login, protected access, logout.

---

## Architecture

### Project Structure

Forge generates an organized **monorepo** following industry-standard conventions:

```
my-platform/
├── services/                    ← Business domain services
│   ├── users/                     Python/FastAPI + SQLAlchemy + Alembic
│   ├── catalog/                   Node.js/Fastify + Prisma + Zod
│   └── shipping/                  Rust/Axum + SQLx + serde
│
├── apps/                        ← Frontend applications
│   └── frontend/                  Vue 3 / Svelte 5 / Flutter
│
├── infra/                       ← Platform infrastructure
│   ├── keycloak/                  Identity provider (Dockerfile + themes)
│   ├── gatekeeper/                OIDC ForwardAuth proxy
│   └── keycloak-realm.json        Pre-configured realm + users
│
├── tests/                       ← E2E testing suite
│   └── e2e/                       Playwright specs + test platform helpers
│
├── docker-compose.yml           ← Root orchestration (all services)
├── init-db.sh                   ← Per-service database creation
└── README.md
```

### Docker Compose

Traefik is always present as the API gateway. All traffic goes through `http://app.localhost` using hostname-based routing. Each backend has a dedicated migration container that runs before the service starts.

```
Browser → http://app.localhost → Traefik :80
            ├── Host(app.localhost) + /api/users/*          → services/users:5000       (Python/FastAPI)
            ├── Host(app.localhost) + /api/catalog/*         → services/catalog:5001     (Node.js/Fastify)
            ├── Host(app.localhost) + /api/shipping/*        → services/shipping:5002    (Rust/Axum)
            ├── Host(app.localhost)                          → apps/frontend:80          (nginx SPA)
            └── (optional) ForwardAuth                      → infra/gatekeeper          (OIDC proxy)

          PostgreSQL :15432 ← per-service databases (users, catalog, shipping, keycloak)
          Migration containers run before each service starts:
            users-migrate (Alembic) | catalog-migrate (Prisma) | shipping-migrate (sqlx)
```

nginx serves static files and SPA fallback only — all API routing is handled by Traefik. The URL `http://app.localhost` works identically with and without authentication. Scaling works out of the box: `docker compose up --scale users=3` and Traefik auto-load-balances.

### Agentic UI (every frontend, `--include-chat`)

The same AG-UI streaming protocol is implemented in all three frameworks: Vue uses `@ag-ui/client`, Svelte uses the same TypeScript client driven by Svelte 5 runes, and Flutter ships a Dart-native client (Dio SSE + JSON-Patch reducer + Riverpod state).

```
User message → chat store → agent client → HTTP POST (SSE stream)
                                                  |
              SSE events ←──────────────────────────┘
    ├── TEXT_MESSAGE_*    → Chat pane (streaming text deltas)
    ├── TOOL_CALL_*       → Chat pane (tool status chip)
    ├── ACTIVITY_*        → Workspace or canvas pane (registry-resolved component)
    ├── STATE_*           → Shared agent state (JSON-Patch deltas applied)
    └── CUSTOM            → Status bar (cost, context, todos) and HITL prompts
```

| Engine | Renders | Trust level | Communication |
|--------|---------|-------------|---------------|
| `ag-ui` | Framework-native component from registry | Trusted (direct store access) | Props + actions |
| `mcp-ext` | Vue/Svelte: sandboxed iframe via AppBridge. Flutter: native widget (no DOM sandbox available). | Untrusted on web, native on Flutter | postMessage (web) / native callback (Flutter) |

---

## Configuration Reference

<details>
<summary>All CLI flags</summary>

| Flag | Description | Default |
|------|-------------|---------|
| `--config FILE` | YAML/JSON config file (`-` for stdin) | |
| `--project-name NAME` | Project name | `My Platform` |
| `--description DESC` | Project description | `A full-stack application` |
| `--output-dir DIR` | Output directory | `.` |
| `--backend-language LANG` | `python`, `node`, or `rust` | `python` |
| `--backend-name NAME` | Service name for the backend | `backend` |
| `--backend-port PORT` | Backend server port | `5000` |
| `--python-version VER` | `3.13`, `3.12`, or `3.11` | `3.13` |
| `--node-version VER` | `22`, `20`, or `18` | `22` |
| `--rust-edition VER` | `2021` or `2024` | `2024` |
| `--frontend FRAMEWORK` | `vue`, `svelte`, `flutter`, or `none` | `none` |
| `--features LIST` | Comma-separated CRUD entities | `items` |
| `--author-name NAME` | Author name | `Your Name` |
| `--package-manager PM` | `npm`, `pnpm`, `yarn`, or `bun` | `npm` |
| `--frontend-port PORT` | Frontend server port | `5173` |
| `--color-scheme SCHEME` | Initial color scheme (Vue, Svelte, Flutter) | `blue` |
| `--org-name ORG` | Flutter org (reverse domain) | `com.example` |
| `--include-auth` | Enable Keycloak authentication | enabled |
| `--no-auth` | Disable Keycloak authentication | |
| `--include-chat` | Enable AG-UI chat panel | enabled |
| `--include-openapi` | Enable OpenAPI code generation | enabled |
| `--no-e2e-tests` | Skip Playwright E2E test generation | |
| `--keycloak-port PORT` | Keycloak host port | `18080` |
| `--keycloak-realm REALM` | Keycloak realm | derived from name |
| `--keycloak-client-id ID` | Keycloak client ID | derived from name |
| `--yes`, `-y` | Skip confirmation prompts | |
| `--no-docker` | Skip Docker Compose boot | |
| `--quiet`, `-q` | Suppress all progress output | |
| `--verbose`, `-v` | Show full Copier + subprocess output (overrides `--quiet`) | |
| `--json` | Machine-readable JSON result on stdout; `{"error": ...}` envelope on failure | |
| `--completion SHELL` | Print a `bash`, `zsh`, or `fish` completion script to stdout and exit | |

**Precedence:** CLI flags > config file values > defaults.

**Exit codes:** `0` success · `1` user cancelled · `2` config/validation/generation error.

</details>

<details>
<summary>Backend languages</summary>

| Language | Framework | ORM / Database | Validation | Migration Container | Tooling |
|----------|-----------|----------------|------------|---------------------|---------|
| Python | FastAPI | SQLAlchemy 2.0 + asyncpg | Pydantic | `{name}-migrate` runs Alembic | uv, Ruff, ty |
| Node.js | Fastify 5 | Prisma 6 | Zod | `{name}-migrate` runs Prisma Migrate | pnpm, Biome, tsc |
| Rust | Axum 0.8 | SQLx 0.8 | serde | `{name}-migrate` runs sqlx binary | Cargo, clippy, rustfmt |

All backends generate the same API contract: `GET /api/v1/health/live`, `GET /api/v1/health/ready`, full CRUD on `/api/v1/{entity}`. The entity name is parameterized from `BackendConfig.features`.

</details>

<details>
<summary>Frontend frameworks</summary>

| Framework | Package Managers | Key Technologies |
|-----------|------------------|-----------------|
| Vue 3 | npm, pnpm, yarn | Vite, TanStack Vue Query, Zod, Vue Router, Pinia, Tailwind 4, AG-UI, MCP ext-apps, workspace + canvas panes |
| Svelte 5 | npm, pnpm, bun | SvelteKit, Vite, TanStack Svelte Query, Zod, runes, Tailwind 4, AG-UI (`@ag-ui/client`), MCP ext-apps, workspace + canvas panes, OpenAPI TypeScript |
| Flutter | N/A (Dart) | Riverpod, GoRouter, freezed, Material 3, FlexColorScheme, Dart-native AG-UI client (Dio SSE + JSON-Patch reducer), workspace + canvas panes |

</details>

<details>
<summary>Default ports and credentials</summary>

All services are accessed through `http://app.localhost` (Traefik on port 80). Direct ports are for debugging only.

| Service | Port | Username | Password |
|---------|------|----------|----------|
| Traefik (gateway) | `80` | — | — |
| Traefik Dashboard | `19090` | — | — |
| Backend API (direct) | `5000+` | — | — |
| PostgreSQL | `15432` | `postgres` | `postgres` |
| Keycloak Admin | `18080` | `admin` | `admin` |
| Sample User | — | `dev@localhost` | `devpass` |
| pgAdmin | `5050` | `admin@localhost.com` | `admin` |
| Gatekeeper Secret | — | — | `gatekeeper-dev-secret` |

</details>

<details>
<summary>What each entity generates</summary>

**Python backend** — domain model, ORM model, repository (tenant-scoped), service, REST endpoints, Gatekeeper header auth, unit tests, integration tests.

**Node.js backend** — Prisma model (snake_case), Zod schema, tenant middleware, service (scoped by `customer_id`), Fastify routes, S2S HTTP client, unit tests, integration tests.

**Rust backend** — SQLx model, TenantContext extractor, service (scoped by `customer_id`), Axum routes, S2S client, SQL migration, integration tests.

**Vue frontend** — Vue Query composable, Zod schema, schema tests, list/create/detail pages (with `data-test` selectors), AlertDialog for delete confirmation, barrel export, MSW mock handlers.

**Svelte frontend** — TanStack Svelte Query hooks, Zod schema, filter/form runes (`{singular}-filters.svelte.ts`, `{singular}-form.svelte.ts`), card component, list / detail / create routes under `(app)/{plural}/`, error boundary, MSW mock handlers, hub-injected sidebar/breadcrumb/dashboard chip.

**Flutter frontend** — Riverpod `AsyncNotifier` controller, `freezed` query params, repository wrapping the OpenAPI-generated client (or Dio directly), list/detail/create pages with form validation, card and form widgets, GoRoute definitions injected into `app_router.dart`, repository unit tests with mocktail.

For multi-backend projects, every per-feature API path is automatically prefixed with the owning backend (`/api/{backend}/v1/{entity}`) — Svelte injects the per-target Vite proxy block; Flutter writes `lib/src/core/config/backend_routes.dart` with the entity → backend lookup.

</details>

---

## Support

- **Issues:** [github.com/cchifor/forge/issues](https://github.com/cchifor/forge/issues)
- **Discussions:** [github.com/cchifor/forge/discussions](https://github.com/cchifor/forge/discussions)

---

## Roadmap

- [ ] Go (Gin/Fiber) backend template
- [ ] React frontend template
- [ ] OpenAPI spec generation from all backends
- [ ] GitHub Actions CI/CD template generation
- [ ] Kubernetes manifests generation
- [ ] Plugin system for custom templates

---

## Contributing

We welcome contributions of all sizes — from typo fixes to new backend templates.

### Development setup

```bash
git clone https://github.com/cchifor/forge.git
cd forge
uv sync --all-extras --dev      # install dependencies (incl. ruff, ty, pre-commit)
uv run pre-commit install       # optional: ruff + ty on every commit
make check                      # lint + typecheck + tests (~10s, 200 tests, ~78% coverage)
uv run forge                    # run locally
```

### Requirements

- Python 3.11+ (CI matrix covers 3.11, 3.12, 3.13 on Linux + Windows)
- `uv` package manager
- Docker (for smoke tests and the e2e harness)

### Environment variables

None required for development. Tests use temporary directories and mock all external calls.

### Commands

| Command | Purpose |
|---------|---------|
| `make check` | Lint + typecheck + unit tests (one shot) |
| `make test` | Run unit tests (excludes `-m e2e`) |
| `make e2e` | Run end-to-end tests that scaffold a project and run its native suite |
| `make lint` | `ruff check forge/` |
| `make format` | `ruff format forge/` |
| `make typecheck` | `ty check forge/` |
| `pre-commit run --all-files` | Run all pre-commit hooks against the tree |

### Contribution workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make changes and run `make check` (lint + typecheck + tests)
4. Open a pull request against `main` — CI runs the full matrix on Linux + Windows

---

## Authors and Acknowledgment

- **Constantin Chifor** — Creator and maintainer

Built with [Copier](https://github.com/copier-org/copier), [Questionary](https://github.com/tmbo/questionary), [Jinja2](https://github.com/pallets/jinja), and [uv](https://docs.astral.sh/uv/).

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Project Status

**Active development.** forge is under active development. The API is stabilizing but breaking changes may occur before v1.0. Contributions and feedback are welcome.