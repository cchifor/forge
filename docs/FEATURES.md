# Option Registry

Forge's configuration surface is a single typed `Option` registry
(NixOS / Terraform style) that compiles into a set of template
**fragments**. This document is for contributors adding a new knob.
End users configure options via YAML (`options:` block), the `--set
PATH=VALUE` CLI flag, or the interactive prompt; machine users can
export the whole schema with `forge --schema` (JSON Schema 2020-12).

## The two layers

```
┌───────────────────────────────────────────────┐
│  Option (user-facing)                         │  forge/options.py
│    path: "rag.backend"                        │
│    type: ENUM, default: "none"                │
│    options: ("none", "pgvector", "qdrant", …) │
│    enables: { "qdrant": ("rag_pipeline",      │
│                          "rag_qdrant",        │
│                          "conversation_…") }  │
└──────────────────────┬────────────────────────┘
                       │ (compiled by capability_resolver)
                       ▼
┌───────────────────────────────────────────────┐
│  Fragment (internal)                          │  forge/fragments.py
│    name: "rag_qdrant"                         │
│    implementations: { PYTHON: ImplSpec(…) }   │
│    depends_on: ("rag_pipeline",)              │
│    capabilities: ("qdrant",)                  │
└───────────────────────────────────────────────┘
```

- **Options** are the human / agent surface. Dotted paths, typed
  leaves (`bool` / `enum` / `int` / `str` / `list`), JSON-Schema
  emitter.
- **Fragments** are the implementation detail. Each fragment lives
  under its owning feature: `forge/features/<ns>/templates/<name>/<backend>/`
  for the template tree plus a `Fragment` entry in
  `forge/features/<ns>/fragments.py`. (Plugins follow the same shape
  inside their own package — see `docs/plugin-development.md`.)

Options enumerate fragments. Fragments never surface to the user.

## What an Option is

An `Option` (in `forge/options.py`) describes one configurable knob.
It declares:

- A unique dotted `path` (e.g. `"rag.backend"`, `"middleware.rate_limit"`).
- A `type` (`BOOL`, `ENUM`, `INT`, `STR`, `LIST`).
- A `default` matching the type.
- A `summary` (one-line, shown in `forge --list`) and `description`
  (multi-line, shown in `forge --describe <path>`).
- A `category` (`FeatureCategory.OBSERVABILITY`, etc. — see the
  category map in `options.py`).
- For ENUM: an `options` tuple of allowed values.
- An `enables` map — `value → (fragment_name, …)` — that compiles to
  the set of fragments to add to the plan.
- Optional JSON-Schema-style constraints: `min` / `max` (INT),
  `pattern` (STR), `hidden` (suppress from default `--list` view).

The registry (`OPTION_REGISTRY`) is the single source of truth for
`cli.py`, `capability_resolver.py`, `forge_toml.py`, and the JSON
Schema emitter.

## What a Fragment is

A `Fragment` (in `forge/fragments.py`) describes the template
realisation of zero-or-more Options' `enables` entries. It declares:

- A unique `name` (e.g. `"rag_qdrant"`).
- Per-backend `FragmentImplSpec` entries — a mapping
  `BackendLanguage → FragmentImplSpec`. A missing entry means
  "unsupported on this backend."
- Optional `depends_on` (fragment names that must be in the plan too).
- Optional `conflicts_with` (mutual exclusion).
- Optional `capabilities` (`"redis"`, `"postgres-pgvector"`, …). The
  docker-compose renderer reads these to provision shared infra.
- Optional `order` (middleware layering within a topological tier).

The `capability_resolver` produces an ordered `ResolvedPlan` — each
fragment in topological order, tied to the backends it supports in the
current project.

## Fragment layout on disk

```
forge/features/<feature_namespace>/
    __init__.py
    options.py              # register_option(...) calls
    fragments.py            # register_fragment(...) calls — passes
                            # absolute fragment_dir paths via
                            # Path(__file__).resolve().parent / "templates"
    templates/<fragment_name>/<backend_lang>/
        files/              # verbatim files to add (must not already exist)
        inject.yaml         # list of (target, marker, snippet) injections
        deps.yaml (optional)  # FragmentImplSpec.dependencies preferred
        env.yaml  (optional)  # FragmentImplSpec.env_vars preferred
```

### Files

Everything under `files/` is copied verbatim into the generated
backend, preserving the relative path. The injector *refuses* to
overwrite an existing file — if you need to modify a file that the
base template already ships, use `inject.yaml` instead.

### Injections

`inject.yaml` is a list of mappings. Each one says: "find this marker
in that file, put this snippet there."

```yaml
- target: src/app/main.py
  marker: FORGE:MIDDLEWARE_IMPORTS
  position: before            # "before" or "after"
  snippet: "from app.middleware.correlation import CorrelationIdMiddleware"
```

Rules:

- **Markers are strict.** A marker that isn't found raises
  `GeneratorError`. A duplicate marker also raises. Each marker must
  appear exactly once per file.
- **Indentation is inherited.** The snippet is indented to match the
  marker line.
- **Multi-line snippets** keep their relative indentation and gain the
  marker's absolute indentation.
- **`position: before`** pushes the snippet above the marker line;
  `after` (default) below. The marker itself is always preserved so
  `forge --update` can find it again.
- **Injections are wrapped in BEGIN/END sentinels** so `forge --update`
  can replace a block in-place instead of duplicating.

### Dependencies

Declared on `FragmentImplSpec.dependencies`. Format is per-language:

- **Python**: PEP 508 specs (`"slowapi>=0.1.9"`). Injected into
  `pyproject.toml` `[project].dependencies` via `tomlkit`, preserving
  existing comments.
- **Node**: `"name@version"` or `"@scope/name@version"`. Merged into
  `package.json`'s `dependencies` dict.
- **Rust**: `"name@version"` or the full-TOML form (`"sha2 = { version
  = \"0.10\", default-features = false }"`). Merged into
  `Cargo.toml`'s `[dependencies]` table.

All three editors are idempotent — re-running is safe.

### Env vars

Tuples of `(KEY, "value")`. Appended to `.env.example`, once per key.

## Standard markers

Base templates ship these marker comments. Adding a new marker
requires updating every base template that claims to support the
fragment.

| Marker | Where | What goes here |
|---|---|---|
| `FORGE:MIDDLEWARE_IMPORTS` | top of `src/app/main.py` (Python) | Middleware class imports |
| `FORGE:MIDDLEWARE_REGISTRATION` | inside `_configure_middleware()` | `app.add_middleware(...)` calls |
| `FORGE:ROUTER_REGISTRATION` | inside `_configure_routers()` | `app.include_router(...)` calls |
| `FORGE:EXCEPTION_HANDLERS` | inside `_configure_exceptions()` | `app.add_exception_handler(...)` calls |
| `FORGE:LIFECYCLE_STARTUP` / `FORGE:LIFECYCLE_SHUTDOWN` | `core/lifecycle.py` | Startup/shutdown hooks |

## Adding an option + fragment in seven steps

1. **Register the Option** in `forge/options.py`. Pick a dotted path
   under the right namespace (`middleware.*`, `observability.*`,
   `async.*`, `conversation.*`, `agent.*`, `chat.*`, `rag.*`,
   `platform.*`), a type, a default, summary / description,
   `FeatureCategory`, and the `enables` map that ties values to
   fragment names.

2. **Register the Fragment** in `forge/fragments.py`. Declare the
   per-backend `FragmentImplSpec` entries, any `depends_on` /
   `conflicts_with` / `capabilities`.

3. **Author the fragment directory** at
   `forge/features/<feature_namespace>/templates/<name>/<backend>/`.
   Start with `files/` for anything new and `inject.yaml` for
   modifications to base-template files. The owning `fragments.py`
   passes the absolute directory path via
   `Path(__file__).resolve().parent / "templates" / "<name>" / "<backend>"`.

4. **Add any new markers** to every base template that supports the
   fragment, *before* your injector tries to use them.

5. **Wire new infrastructure.** If the fragment brings new infra
   (Redis, a vector store, …), add the `capabilities` entry and make
   sure `forge/docker_manager.py`'s compose renderer knows what to
   provision for it.

6. **Write tests.** The registry invariants in `tests/test_options.py`
   automatically pick up the new Option. Add a resolver test that your
   Option's values map to the expected fragment set, plus an injector
   test if the fragment does anything non-obvious.

7. **Document it.** Add a row to this file's [registered options](#registered-options)
   list and a short blurb in `README.md`.

## User configuration

End users set options three ways:

**1. YAML config** — `options:` block, dotted or nested.

```yaml
options:
  middleware.rate_limit: false
  rag.backend: qdrant
  rag.top_k: 10

# Nested form also accepted (normalised on load):
options:
  middleware:
    rate_limit: false
  rag:
    backend: qdrant
    top_k: 10
```

**2. `--set` CLI flag** — repeatable, highest precedence.

```bash
forge --set rag.backend=qdrant \
      --set rag.embeddings=voyage \
      --set rag.top_k=10 \
      --set agent.llm=true
```

Values are coerced to the Option's native type (`true` → bool, `10` →
int) before validation.

**3. Interactive mode** — `forge` with no args walks the user through
project-level prompts. Option toggles live in YAML / CLI flags only
(no prompt-per-option bloat).

## Registered options

Options are grouped by `FeatureCategory` — same order
`forge --list` prints and `forge --describe` narrates. Run
`forge --describe <path>` for the full prose + tag lines
(`BACKENDS:` / `ENDPOINTS:` / `REQUIRES:`) per option.

### Observability — visibility into the running system

| Path | Type | Default | Backends | Summary |
|---|---|---|---|---|
| `middleware.correlation_id` | enum | `always-on` | python | X-Request-ID header + ContextVar propagation |
| `observability.health` | bool | `false` | python, node, rust | /health aggregates DB + Redis + Keycloak readiness |
| `observability.tracing` | bool | `false` | python, node, rust | Logfire (Py) / OTel SDK (Node) / OTLP gRPC (Rust) |

Enable these when you need to trace a request hop across services,
gate rollouts on actual dependency health, or ship structured traces
into an OTLP collector.

### Reliability — protection + stability middleware

| Path | Type | Default | Backends | Summary |
|---|---|---|---|---|
| `middleware.rate_limit` | bool | `true` | python, node, rust | Token-bucket limiter keyed by tenant / IP |
| `middleware.security_headers` | bool | `true` | python, node, rust | CSP + XFO + HSTS + Referrer-Policy + Permissions-Policy |
| `middleware.pii_redaction` | bool | `true` | python | logging.Filter that redacts emails / tokens / API keys |
| `middleware.response_cache` | bool | `false` | python, node | fastapi-cache2 + Redis (Py) / @fastify/caching (Node) |

The on-by-default entries are there for a reason; turn them off only
for intentional insecure-demo scenarios. Response cache is opt-in —
decorate specific handlers rather than blanket-enabling.

### Async Work — off-thread job processing

| Path | Type | Default | Backends | Summary |
|---|---|---|---|---|
| `async.task_queue` | bool | `false` | python, node, rust | Taskiq (Py) / BullMQ + ioredis (Node) / Apalis + Redis (Rust) |
| `async.rag_ingest_queue` | bool | `false` | python | Taskiq tasks that move RAG ingest off the request thread |

Reach for these when you've got work a user shouldn't wait on —
emails, webhook retries, RAG ingestion, LLM fan-outs. Node and Rust
variants share the `TASKIQ_BROKER_URL` env convention so docker-compose
ops stay uniform across backends.

### Conversational AI — chat, tools, and the agent loop

| Path | Type | Default | Backends | Summary |
|---|---|---|---|---|
| `conversation.persistence` | bool | `false` | python | SQLAlchemy Conversation/Message/ToolCall + migration |
| `agent.streaming` | bool | `false` | python | /api/v1/ws/agent WebSocket with typed events + runner dispatch |
| `agent.tools` | bool | `false` | python | Tool base class + process registry + /api/v1/tools |
| `agent.llm` | bool | `false` | python | pydantic-ai loop (Anthropic / OpenAI / Google / OpenRouter) |
| `chat.attachments` | bool | `false` | python | /api/v1/chat-files + ChatFile model + local storage |

Order of introduction: enable `conversation.persistence` first
(storage), then `agent.streaming` (WebSocket + echo runner), then
`agent.tools` + `agent.llm` (LLM loop), then `chat.attachments` if you
need attachments. The `rag_search` agent tool auto-registers when RAG
is also on.

### Knowledge — vector storage + retrieval (RAG)

| Path | Type | Default | Backends | Summary |
|---|---|---|---|---|
| `rag.backend` | enum | `none` | python | Pick one: `none` / `pgvector` / `qdrant` / `chroma` / `milvus` / `weaviate` / `pinecone` / `postgresql` |
| `rag.embeddings` | enum | `openai` | python | `openai` (text-embedding-3-small) or `voyage` (voyage-3.5) |
| `rag.reranker` | bool | `false` | python | Cohere rerank + local cross-encoder fallback for sharper top-K |
| `rag.top_k` | int (1–100) | `5` | python | Default chunks returned per RAG query |

`rag.backend` is a single enum with eight values — each value bundles
the matching fragment (`rag_qdrant`, `rag_chroma`, …) alongside the
shared `rag_pipeline` + required `conversation_persistence`. No need
to hand-pick the transitive dependency chain.

### Platform — operator-facing tooling

| Path | Type | Default | Backends | Summary |
|---|---|---|---|---|
| `platform.admin` | bool | `false` | python | SQLAdmin UI at /admin, env-gated, auto-registers views |
| `platform.webhooks` | bool | `false` | python, node, rust | Registry + HMAC-SHA256 signed delivery + /test endpoint |
| `platform.cli_extensions` | bool | `false` | python | `app info` / `app tools` / `app rag` typer subcommands |
| `platform.agents_md` | bool | `true` | all (project-scoped) | Drops AGENTS.md + CLAUDE.md at project root |

Operator UX — human admins browsing data, event fan-out for
third-party integrators, SSH-in shell commands, and guidance docs for
AI coding agents contributing to the generated repo.

Run `forge --list` for the up-to-date list (flat columnar table by
default; pair with `--format json` / `--format yaml` for
machine-readable output), or `forge --describe <path>` for the full
prose + metadata of any single option.

## Layer discriminators — composing a project

Four **layer-mode** options control what forge generates, one per
major layer. Each is an ENUM with `generate` / `external` / `none`
values (subset varies by layer) and an empty `enables` map — the mode
orchestrates generation, it doesn't enable a fragment bundle.

| Path | Options | Default | Purpose |
|---|---|---|---|
| `backend.mode` | `generate`, `none` | `generate` | Skip backend scaffolding entirely. Pair with `frontend.api_target.url` for a frontend-only project pointed at an external API. |
| `database.mode` | `generate`, `none` | `generate` | Skip the postgres container + per-backend migrate sidecars. Use for stateless services. Incompatible with DB-backed options (`conversation.persistence`, `rag.backend != none`, `platform.admin`, etc.). |
| `frontend.mode` | `generate`, `external`, `none` | `generate` | `none` skips frontend generation (coherent with `FrontendFramework.NONE`). `external` is reserved for wiring a thin wrapper at an existing deployed frontend. |
| `agent.mode` | `generate`, `external`, `none` | `none` | Placeholder — pattern parity with the other layers. Real wiring lands when the agentic stack gets its own generate/external scenarios. |

### `frontend.api_target`

Structured pair that controls the URL the generated frontend talks
to. Used by both `backend.mode=none` and any project that wants to
point the frontend at a non-local API.

| Path | Type | Default | Purpose |
|---|---|---|---|
| `frontend.api_target.type` | enum (`local` / `external`) | `local` | Whether Vite proxy routes `/api/*` to a Docker-internal backend or bypasses the proxy for an external URL. |
| `frontend.api_target.url` | str | `""` | Base URL used when `type=external` or `backend.mode=none`. Empty string means fall back to local inference. |

The Phase A flat path `frontend.api_target_url` is a deprecated alias
of `frontend.api_target.url`. Existing `forge.toml` files continue to
work; the resolver rewrites the alias and emits a warning.

### Canonical scenarios

- **Frontend-only** (`backend.mode=none`, `frontend.api_target.url=https://api.example.com`) — no `services/`, no postgres, no migrate sidecars. Compose ships frontend + traefik + optional keycloak.
- **Stateless backend** (`database.mode=none`) — backend container still renders, but no postgres, no alembic migration wiring in compose. Backends consuming no DB.
- **Local backend + external API target** (`frontend.api_target.type=external`, `frontend.api_target.url=…`) — backends run locally (for non-API work), frontend dev server points at a staging/prod API.

## JSON Schema export

`forge --schema` emits the JSON Schema 2020-12 document for the whole
registry. Agents (and humans) can validate a proposed config locally
before invoking forge:

```bash
forge --schema > forge-options.schema.json
python -c 'import json, jsonschema; jsonschema.Draft202012Validator.check_schema(json.load(open("forge-options.schema.json")))'
```

Every registered Option becomes a property on the top-level object.
Enums carry their value list, ints carry `minimum`/`maximum`, strings
carry `pattern` — standard JSON-Schema vocabulary.

## Fragment scopes

A fragment's `FragmentImplSpec.scope` decides where it's applied:

- **`backend`** (default) — applied once per supporting backend
  directory. Use for per-service middleware, route additions,
  dependency edits.
- **`project`** — applied once to the project root after all backends
  are generated. Use for cross-cutting files (`AGENTS.md`, shared
  Makefile, root-level CI workflows). Registered under every backend
  key but emits a single time.

## Roadmap — not yet shipped

These backends/variants don't have a `FragmentImplSpec` yet.
Configuration will be purely additive when they land, so existing
projects see no behavior change.

- **`response_cache/rust`** — no clear canonical library yet; roll
  your own with `moka` + a tower `Layer`.
- **`webhooks/rust` durable registry** — axum + sqlx-backed
  persistence (in-memory v1 already shipped).
- **`cli_commands/node`** — npm scripts already cover the surface;
  explicit subcommands planned once a CLI framework like `citty` lands.
- **`cli_commands/rust`** — clap-based subcommand layer on top of the
  existing `src/bin/migrate.rs` pattern.
- **Additional embeddings providers** beyond OpenAI + Voyage — Cohere
  embed, local `sentence-transformers`. Same pattern as the existing
  `rag_embeddings_voyage` fragment.
- **`security_ratelimit_strict`** — composite preset bundling
  `middleware.rate_limit` + `middleware.security_headers` +
  tightened CORS.

## Design note — middleware ordering

`Fragment.order` controls layering within a topological dependency
tier. Convention for Starlette/Axum-family middleware stacks where
**later-added = outer**:

- Assign numeric `order` ascending from *innermost* to *outermost*.
- Fragments use `position: before` on the `MIDDLEWARE_REGISTRATION`
  marker so earlier-resolved fragments land higher in the file
  (innermost) and later-resolved (higher `order`) fragments land just
  above the marker (outermost).

Current Python stack, innermost → outermost:

1. base: `RequestLoggingMiddleware` (hardcoded)
2. base: `AuditMiddleware` (conditional, hardcoded)
3. fragment `rate_limit` (`order=50`)
4. fragment `security_headers` (`order=80`)
5. fragment `correlation_id` (`order=90`, outermost)

Current Node stack, innermost → outermost (Fastify registration order):

1. base: `@fastify/cors`, correlation/tenant/logger hooks, errorHandler
2. fragment `rate_limit` (`order=50`) — `@fastify/rate-limit`
3. fragment `security_headers` (`order=80`) — `@fastify/helmet`

Current Rust stack (Axum layer order, outermost first):

1. base: correlation (propagate + set request-id), CORS
2. fragment `security_headers` — `axum::middleware::from_fn`
