<div align="center">

# forge

*Production-ready full-stack project generator with 3 backend languages, 3 frontend frameworks, and enterprise auth — from a single command.*

[Quick Start](#quick-start) · [Features](#features) · [Usage](#usage-examples) · [Architecture](#architecture) · [Contributing](#contributing)

[![version](https://img.shields.io/badge/version-0.1.0-blue?style=flat-square)](https://github.com/cchifor/forge) [![python](https://img.shields.io/badge/python-%3E%3D3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org) [![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE) [![platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macos-lightgrey?style=flat-square)](https://github.com/cchifor/forge) [![tests](https://img.shields.io/badge/tests-137%20passed-brightgreen?style=flat-square)](https://github.com/cchifor/forge)

**3 Backend Languages** *(Python/FastAPI, Node.js/Fastify, Rust/Axum)*
**3 Frontend Frameworks** *(Vue 3, Svelte 5, Flutter)*
**Agentic UI** *(AG-UI protocol, MCP ext-apps, dual-engine workspace)*
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
| **Backend Choice** | Python ([FastAPI](https://fastapi.tiangolo.com) + SQLAlchemy + Alembic), Node.js ([Fastify 5](https://fastify.dev) + Prisma 6 + Zod), or Rust ([Axum 0.8](https://github.com/tokio-rs/axum) + SQLx + serde). All three produce the same REST API contract. |
| **Frontend Choice** | [Vue 3](https://vuejs.org), [Svelte 5](https://svelte.dev), [Flutter](https://flutter.dev) (web), or none. Each includes TanStack Query / Zod / Vite and a responsive dashboard with health checks. |
| **Full CRUD Generation** | Name your entities (e.g., `products, orders`) and forge generates domain models, ORM models, repositories, services, REST endpoints, API clients, UI pages, schemas, MSW handlers, and tests — for every entity, in every layer. |
| **Agentic UI** | Vue template includes a split-pane workspace with [AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui) (SSE streaming) and [MCP ext-apps](https://github.com/anthropics/ext-apps) (sandboxed iframes). Dual-engine rendering for trusted Vue components and third-party extensions. |
| **Production Docker** | Two-stage Dockerfiles (builder + slim runtime) for every backend and frontend. nginx reverse proxy with SPA fallback. PostgreSQL 16 with health checks. One-shot migration containers. |
| **Authentication** | Toggle `--include-auth` to get: [Keycloak 26](https://www.keycloak.org) identity provider with pre-configured realm, [Gatekeeper](https://github.com/cchifor/forge) OIDC ForwardAuth proxy, [Traefik v2.11](https://traefik.io) edge router, Redis session cache, JWT route guards, user registration, and sample users. |
| **Headless / Agent Mode** | `--config`, `--json`, `--quiet` flags for CI/CD and AI agents. Pipe JSON from stdin, get structured output on stdout. No TTY required. Works with `uvx` for zero-install execution. |
| **Testing** | Pytest (Python), Vitest (Node.js), Cargo test (Rust), Vitest (Vue/Svelte), Flutter test. Playwright E2E browser tests for auth flows. Docker testcontainers for real PostgreSQL integration tests. |
| **Cross-Platform** | Windows (Git Bash), Linux, macOS. LF line endings enforced for Docker container scripts. |

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

Your app is now running: frontend at `http://localhost:5173`, backend API at `http://localhost:5000/api/v1/health/live`.

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
# stack.yaml
project_name: my-shop
description: An e-commerce platform

backend:
  language: python          # python | node | rust
  server_port: 5000
  python_version: "3.13"    # python only
  # node_version: "22"      # node only
  # rust_edition: "2024"    # rust only

frontend:
  framework: vue            # vue | svelte | flutter | none
  features: products, orders, customers
  package_manager: pnpm
  include_auth: true

keycloak:
  port: 8080
  realm: my-shop
  client_id: my-shop
```

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
{"project_root": "/path/to/my_api", "backend_dir": "/path/to/my_api/backend"}
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

### Validate authentication (after docker compose up)

When auth is enabled, a `validate.sh` script runs Playwright browser tests against the live stack:

```bash
cd my_shop/
docker compose up --build -d
bash validate.sh
```

Expected output:
```
  [ok] Keycloak ready
  [ok] Frontend ready
  [ok] Backend ready

  Running E2E auth validation...

  tests/e2e/test_auth.py::TestLogin::test_login_with_valid_credentials PASSED
  tests/e2e/test_auth.py::TestRegistration::test_register_new_user PASSED
  ...
```

---

## Architecture

### Docker Compose (with auth enabled)

```
Browser → Traefik :80 → ForwardAuth(Gatekeeper) → Backend :5000
                ↓                                       ↑
          Keycloak :8080 ← OIDC code exchange ← Gatekeeper
                                                       ↑
                                                  Redis :6379

          PostgreSQL :5432 ← Backend + Keycloak (shared)
          pgAdmin :5050    (tools profile)
```

### Agentic UI (Vue template, `--include-chat`)

```
User message → useAiChat → useAgentClient → HTTP POST (SSE stream)
                                                    |
              SSE events ←──────────────────────────┘
    ├── TEXT_MESSAGE_*    → Chat pane (streaming text)
    ├── TOOL_CALL_*       → Chat pane (tool status card)
    ├── ACTIVITY_*        → Workspace pane (dynamic component)
    ├── STATE_*           → Shared agent state
    └── CUSTOM            → Status bar (cost, context)
```

| Engine | Renders | Trust level | Communication |
|--------|---------|-------------|---------------|
| `ag-ui` | Vue component from registry | Trusted (direct Pinia/store access) | Props + emits |
| `mcp-ext` | Sandboxed iframe via AppBridge | Untrusted (no store access) | postMessage only |

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
| `--backend-port PORT` | Backend server port | `5000` |
| `--python-version VER` | `3.13`, `3.12`, or `3.11` | `3.13` |
| `--node-version VER` | `22` or `24` | `22` |
| `--rust-edition VER` | `2021` or `2024` | `2024` |
| `--frontend FRAMEWORK` | `vue`, `svelte`, `flutter`, or `none` | `none` |
| `--features LIST` | Comma-separated CRUD entities | `items` |
| `--author-name NAME` | Author name | `Your Name` |
| `--package-manager PM` | `npm`, `pnpm`, `yarn`, or `bun` | `npm` |
| `--frontend-port PORT` | Frontend server port | `5173` |
| `--color-scheme SCHEME` | Vue color scheme | `blue` |
| `--org-name ORG` | Flutter org (reverse domain) | `com.example` |
| `--include-auth` | Enable Keycloak authentication | |
| `--no-auth` | Disable Keycloak authentication | |
| `--include-chat` | Enable AI chat panel | |
| `--include-openapi` | Enable OpenAPI code generation | |
| `--no-e2e-tests` | Skip Playwright E2E test generation | |
| `--keycloak-port PORT` | Keycloak host port | `8080` |
| `--keycloak-realm REALM` | Keycloak realm | derived from name |
| `--keycloak-client-id ID` | Keycloak client ID | derived from name |
| `--yes`, `-y` | Skip confirmation prompts | |
| `--no-docker` | Skip Docker Compose boot | |
| `--quiet`, `-q` | Suppress all progress output | |
| `--json` | Machine-readable JSON result on stdout | |

**Precedence:** CLI flags > config file values > defaults.

**Exit codes:** `0` success · `1` user cancelled · `2` config/validation error.

</details>

<details>
<summary>Backend languages</summary>

| Language | Framework | ORM / Database | Validation | Migrations | Tooling |
|----------|-----------|----------------|------------|------------|---------|
| Python | FastAPI | SQLAlchemy 2.0 + asyncpg | Pydantic | Alembic | uv, Ruff, ty |
| Node.js | Fastify 5 | Prisma 6 | Zod | Prisma Migrate | pnpm, Biome, tsc |
| Rust | Axum 0.8 | SQLx 0.8 | serde | SQLx Migrate | Cargo, clippy, rustfmt |

All backends generate the same API contract: `GET /api/v1/health/live`, `GET /api/v1/health/ready`, full CRUD on `/api/v1/items`.

</details>

<details>
<summary>Frontend frameworks</summary>

| Framework | Package Managers | Key Technologies |
|-----------|------------------|-----------------|
| Vue 3 | npm, pnpm, yarn | Vite, TanStack Query, Zod, Vue Router, AG-UI, MCP ext-apps |
| Svelte 5 | npm, pnpm, bun | SvelteKit, Vite, OpenAPI TypeScript |
| Flutter | N/A (Dart) | Riverpod, GoRouter, freezed |

</details>

<details>
<summary>Default ports and credentials</summary>

| Service | Port | Username | Password |
|---------|------|----------|----------|
| Backend API | `5000` | — | — |
| Frontend (nginx) | `5173` | — | — |
| PostgreSQL | `5432` | `postgres` | `postgres` |
| Keycloak Admin | `8080` | `admin` | `admin` |
| Sample User | — | `dev@localhost` | `devpass` |
| pgAdmin | `5050` | `admin@localhost.com` | `admin` |
| Traefik Dashboard | `8888` | — | — |
| Gatekeeper Secret | — | — | `gatekeeper-dev-secret` |

</details>

<details>
<summary>What each entity generates</summary>

**Python backend** — domain model, ORM model, repository, service, REST endpoints, unit tests, integration tests.

**Node.js backend** — Prisma model, Zod schema, service, Fastify routes, unit tests, integration tests.

**Rust backend** — SQLx model, service, Axum routes, SQL migration, integration tests.

**Vue frontend** — Vue Query composable, Zod schema, schema tests, list/create/detail pages, barrel export, MSW mock handlers.

Svelte and Flutter generate analogous files for their respective frameworks.

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
uv sync                         # install dependencies
uv run pytest -v                # run tests (137 tests, 67%+ coverage)
uv run forge                    # run locally
```

### Requirements

- Python 3.11+
- `uv` package manager
- Docker (for smoke tests)

### Environment variables

None required for development. Tests use temporary directories and mock all external calls.

### Commands

| Command | Purpose |
|---------|---------|
| `uv run pytest -v` | Run all tests |
| `uv run pytest tests/ -m "not docker"` | Skip Docker-dependent tests |
| `uv run ruff check forge/` | Lint |
| `uv run ruff format forge/` | Format |
| `uv run ty check forge/` | Type check |

### Contribution workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make changes and ensure tests pass: `uv run pytest -v`
4. Open a pull request against `main`

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