# forge-cli

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-%3E%3D3.11-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macos-lightgrey)

Generate production-ready backends, frontends, or full-stack applications -- wired together with Docker Compose -- from a single command.

<!-- TODO: Replace the ASCII block below with an Asciinema/VHS terminal recording GIF -->

---

## Getting Started

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/cchifor/forge-cli/main/install | bash
```

The installer checks for `uv`, `git`, and `docker`, asks before installing anything missing, then installs forge globally. On Windows, run from **Git Bash** ([Git for Windows](https://git-scm.com/downloads/win)) -- it automatically delegates to PowerShell for native operations.

**Prerequisites**: `uv` (installed automatically), Git, Docker. Node.js 22+ for Vue/Svelte frontends. Flutter SDK only if generating Flutter.

<details>
<summary>Other install methods</summary>

```bash
# Global (if you already have uv)
uv tool install git+https://github.com/cchifor/forge-cli.git

# Development
git clone https://github.com/cchifor/forge-cli.git
cd forge-cli && python sync_templates.py && uv sync
uv run forge
```

</details>

### Headless (scripts, CI/CD, AI agents)

Run forge without installing it and without interactive prompts -- a single command that generates a project and exits:

```bash
uvx --from git+https://github.com/cchifor/forge-cli.git forge \
  --config stack.yaml --yes --no-docker
```

Or pipe JSON directly from an AI agent (no file on disk):

```bash
echo '{"project_name":"my-shop","frontend":{"framework":"vue","features":"products,orders"}}' \
  | uvx --from git+https://github.com/cchifor/forge-cli.git forge --config - --yes --no-docker
```

`uvx` downloads forge into a temporary cached environment, runs it, and exits. No global install needed. See [Usage > Headless](#headless-scripts-cicd-ai-agents) for the full config file format and all CLI flags.

---

## Usage

### Interactive (human developers)

```bash
forge
```

Follow the prompts to pick a backend, a frontend (or `None`), CRUD entities, and feature toggles.

### Headless (scripts, CI/CD, AI agents)

Run without prompts by passing a config file, CLI flags, or both. Add `--yes` to skip confirmation and `--no-docker` to skip the Docker boot step.

**From a YAML config file:**

```bash
forge --config stack.yaml --yes --no-docker
```

```yaml
# stack.yaml
project_name: my-shop
description: An e-commerce platform

backend:
  server_port: 5000
  python_version: "3.13"

frontend:
  framework: vue          # vue | svelte | flutter | none
  features: products, orders, customers
  author_name: Jane Doe
  package_manager: pnpm   # npm | pnpm | yarn | bun
  server_port: 5173
  include_auth: true
  include_chat: false
  include_openapi: false
  default_color_scheme: indigo  # vue only
  # org_name: com.example       # flutter only

keycloak:
  port: 8080
  realm: master
  client_id: my-shop
```

**From CLI flags (no file needed):**

```bash
forge --project-name my-shop --frontend vue --features "products,orders" --yes
```

**Pipe JSON from stdin (AI agents):**

```bash
echo '{"project_name":"my-shop","frontend":{"framework":"vue","features":"products,orders"}}' \
  | forge --config - --yes --no-docker
```

<details>
<summary>All CLI flags</summary>

| Flag | Description | Default |
|---|---|---|
| `--config FILE` | YAML/JSON config file (`-` for stdin) | |
| `--project-name NAME` | Project name | `My Platform` |
| `--description DESC` | Project description | `A full-stack application` |
| `--output-dir DIR` | Output directory | `.` |
| `--backend-port PORT` | Backend server port | `5000` |
| `--python-version VER` | `3.13`, `3.12`, or `3.11` | `3.13` |
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
| `--keycloak-port PORT` | Keycloak host port | `8080` |
| `--keycloak-realm REALM` | Keycloak realm | `master` |
| `--keycloak-client-id ID` | Keycloak client ID | derived from name |
| `--yes`, `-y` | Skip confirmation prompts | |
| `--no-docker` | Skip Docker Compose boot | |

CLI flags override config file values. Config file values override defaults.

</details>

### After generation

```bash
cd my_shop/
docker compose up --build          # start the stack
docker compose --profile tools up  # include pgAdmin
docker compose down --volumes      # stop and clean up
```

### Default credentials

| Service    | Username                | Password     |
| ---------- | ----------------------- | ------------ |
| PostgreSQL | `postgres`            | `postgres` |
| Keycloak   | `admin`               | `admin`    |
| pgAdmin    | `admin@localhost.com` | `admin`    |

---

## What You Can Generate

```
Backend only                 Frontend only              Full stack
(Python/FastAPI + DB)        (Vue, Svelte, or Flutter)  (Backend + Frontend + DB)

+-------------+              +-------------+            +-------------+
|  backend    |              |  frontend   |            |  frontend   |
|  :5000      |              |  :5173      |            |  :5173      |
+------+------+              +-------------+            +------+------+
       |                                                       |
+------v------+                                         +------v------+     +-------------+
|  postgres   |                                         |  backend    +---->|  postgres   |
|  :5432      |                                         |  :5000      |     |  :5432      |
+-------------+                                         +------+------+     +-------------+
                                                               |
+-------------+                                         +------v------+
|  keycloak   |  (optional)                             |  keycloak   |  (optional)
|  :8080      |                                         |  :8080      |
+-------------+                                         +-------------+
```

### Features

- **Flexible** -- backend only, frontend only, or full stack from a single command.
- **Four templates** -- Python/FastAPI, Vue 3, Svelte 5, Flutter -- bundled and version-controlled.
- **Full CRUD generation** -- each entity produces domain models, ORM models, repositories, services, REST endpoints, API clients, UI pages, and tests.
- **Unified Docker Compose** -- renders only the services you selected.
- **Keycloak integration** -- provisions a dev container, JWT auth, and route guards with one toggle.
- **Cross-platform** -- Windows, Linux, macOS.

### Tech Stack

| Layer             | Technologies                                                                                                                                       |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CLI**     | Python 3.11+,[Copier](https://github.com/copier-org/copier), [Questionary](https://github.com/tmbo/questionary), [Jinja2](https://github.com/pallets/jinja) |
| **Backend** | FastAPI, SQLAlchemy, Alembic, Pydantic, Dishka (DI), uv                                                                                            |
| **Vue**     | Vue 3, Vite, TanStack Query, Zod, Vue Router                                                                                                       |
| **Svelte**  | SvelteKit, Vite, OpenAPI TypeScript                                                                                                                |
| **Flutter** | Flutter, Dart, Riverpod                                                                                                                            |
| **Infra**   | Docker Compose, PostgreSQL 16, Keycloak 26, pgAdmin 4                                                                                              |

---

## Architecture

### Docker Compose

All services run on a shared `app-network` bridge. The frontend proxies `/api` to the backend via Docker DNS.

```
+-------------+     +-------------+     +-------------+
|  frontend   |---->|  backend    |---->|  postgres   |
|  :5173      |     |  :5000      |     |  :5432      |
+-------------+     +------+------+     +-------------+
                           |
                    +------v------+
                    |  keycloak   |  (if auth enabled)
                    |  :8080      |
                    +-------------+

                    +-------------+
                    |  pgadmin    |  (tools profile)
                    |  :5050      |
                    +-------------+
```

**Flutter exception**: Flutter projects are generated but excluded from Docker Compose. Run natively with `flutter run`.

### Generated project structure

```
acme/
├── docker-compose.yml
├── backend/                    # Python / FastAPI
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/
│   ├── config/
│   ├── src/
│   │   ├── service/            # Shared infrastructure
│   │   └── backend/            # Application code
│   │       ├── api/v1/
│   │       ├── data/models/
│   │       ├── domain/
│   │       └── services/
│   └── tests/
└── frontend/                   # Vue 3 / Svelte 5
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts
    └── src/
```

### Configuration reference

<details>
<summary>Frontend frameworks</summary>

| Choice   | Template                      | Package managers |
| -------- | ----------------------------- | ---------------- |
| Vue 3    | `vue-frontend-template`     | npm, pnpm, yarn  |
| Svelte 5 | `svelte-frontend-template`  | npm, pnpm, bun   |
| Flutter  | `flutter-frontend-template` | N/A              |
| None     | --                            | --               |

</details>

<details>
<summary>Feature toggles</summary>

| Toggle                  | Scope         | Default | Effect                                     |
| ----------------------- | ------------- | ------- | ------------------------------------------ |
| Keycloak authentication | Frontend      | Yes     | JWT auth, Keycloak container, route guards |
| AI chat panel           | Frontend      | No      | Chat panel component                       |
| OpenAPI code generation | Vue / Flutter | No      | Generated API client from OpenAPI spec     |

</details>

<details>
<summary>Entity naming rules</summary>

Entity names must be lowercase (`^[a-z][a-z0-9_]*$`), not Python keywords, not duplicated, and not a reserved name: `auth, home, profile, settings, chat, core, shared, shell, dashboard, tasks, app, test, lib, routes, api`.

</details>

<details>
<summary>What each entity generates</summary>

**Backend** -- 7 files: domain model, ORM model, repository, service, REST endpoints, unit tests, integration tests.

**Vue** -- 8 files: Vue Query composable, Zod schema, schema tests, list/create/detail pages, barrel export, MSW handlers.

Svelte and Flutter generate analogous files.

</details>

<details>
<summary>Default ports</summary>

| Service    | Port     |
| ---------- | -------- |
| Backend    | `5000` |
| Frontend   | `5173` |
| PostgreSQL | `5432` |
| pgAdmin    | `5050` |
| Keycloak   | `8080` |

</details>

---

## Development

### Project structure

```
forge-cli/
├── install                     # Cross-platform installer (curl | bash)
├── pyproject.toml
├── forge/
│   ├── cli.py                  # Interactive prompts and entry point
│   ├── config.py               # Dataclasses, enums, validation
│   ├── variable_mapper.py      # Config -> per-template data dicts
│   ├── generator.py            # Copier orchestration
│   ├── docker_manager.py       # Compose/Dockerfile rendering
│   └── templates/              # Bundled Copier templates
└── tests/
```

### Setup

```bash
git clone https://github.com/cchifor/forge-cli.git
cd forge-cli
python sync_templates.py        # copy templates from parent repo
uv sync                         # install dependencies
uv run pytest -v                # run tests
uv run forge                    # run locally
```

### Template syncing

```bash
python sync_templates.py        # sync from parent repo
python sync_templates.py --clean
```

### Updating a global install

```bash
uv tool upgrade forge-cli
```

---

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feat/my-feature`.
3. Ensure tests pass: `uv run pytest -v`.
4. Open a pull request against `main`.

---

## License

This project is licensed under the [MIT License](LICENSE).
