# Feature Registry

Forge's feature system lets opt-in capabilities — rate limiting, observability,
the agent platform, RAG — compose onto any base project without bloating the
underlying templates. This document is for contributors adding a new feature.
End users configure features via YAML or the `--enable-feature` / `--disable-feature`
CLI flags.

## What a feature is

A `FeatureSpec` (in `forge/features.py`) describes one opt-in (or always-on)
capability. It declares:

- A unique `key` (e.g. `"rate_limit"`).
- A CLI flag name (e.g. `--include-rate-limit`).
- A per-backend `FragmentImplSpec` telling the injector *how* to apply the
  feature to each supported language. A missing entry means "unsupported."
- Optional `depends_on` (feature keys) and `conflicts_with` lists.
- `capabilities` — strings like `"redis"` or `"postgres-pgvector"` that the
  docker-compose renderer uses to emit shared infrastructure services.
- Optional `extra_flags` (sub-flags like `--vector-store qdrant`).
- `default_enabled` / `always_on` policy.

The registry is the single source of truth. `cli.py`, `generator.py`, and
`docker_manager.py` read from it; nothing hardcodes feature logic.

## Fragment layout

Every implementation lives under
`forge/templates/_fragments/<feature_key>/<backend_lang>/`:

```
forge/templates/_fragments/correlation_id/python/
    files/                  # verbatim files to add (must not exist in base)
    inject.yaml             # list of (target, marker, snippet) injections
    deps.yaml   (optional)  # dependencies — v1 uses FragmentImplSpec.dependencies
    env.yaml    (optional)  # env vars   — v1 uses FragmentImplSpec.env_vars
```

### Files

Everything under `files/` is copied into the generated backend verbatim,
preserving the relative path. The injector *refuses* to overwrite an existing
file — if you need to modify a file that the base template already ships,
use `inject.yaml` instead.

### Injections

`inject.yaml` is a list of mappings. Each one says: "find this marker in that
file, put this snippet there."

```yaml
- target: src/app/main.py
  marker: FORGE:MIDDLEWARE_IMPORTS
  position: before            # "before" or "after"
  snippet: "from app.middleware.correlation import CorrelationIdMiddleware"
```

Rules:

- **Markers are strict.** A marker that isn't found raises `GeneratorError`.
  A marker that appears more than once also raises. Write templates that
  place each marker on its own line.
- **Indentation is inherited.** The snippet is indented to match the marker
  line. For a marker inside a function body at 4-space indent, the snippet
  lands at 4-space indent.
- **Multi-line snippets** keep their relative indentation and gain the
  marker's absolute indentation.
- **`position: before`** pushes the snippet above the marker line; `after`
  (default) below. The marker itself is always preserved so future
  regenerations (eventually `forge update`) can find it again.

### Dependencies

Declared on `FragmentImplSpec.dependencies`. Format is per-language:

- **Python**: PEP 508 specs (`"slowapi>=0.1.9"`). Injected into `pyproject.toml`
  `[project].dependencies` via `tomlkit`, preserving existing comments.
- **Node**: `"name@version"` or `"@scope/name@version"`. Merged into
  `package.json`'s `dependencies` dict.
- **Rust**: `"name@version"`. Merged into `Cargo.toml`'s `[dependencies]` table.

All three editors are idempotent — re-running is safe.

### Env vars

Tuples of `(KEY, "value")`. Appended to `.env.example`, once per key.

## Standard markers

Base templates ship these marker comments. Adding a new marker requires
updating every base template that claims to support the feature.

| Marker | Where | What goes here |
|---|---|---|
| `FORGE:MIDDLEWARE_IMPORTS` | top of `src/app/main.py` (Python) | Middleware class imports |
| `FORGE:MIDDLEWARE_REGISTRATION` | inside `_configure_middleware()` | `app.add_middleware(...)` calls |
| `FORGE:ROUTER_REGISTRATION` | inside `_configure_routers()` | `app.include_router(...)` calls |
| `FORGE:EXCEPTION_HANDLERS` | inside `_configure_exceptions()` | `app.add_exception_handler(...)` calls |
| `FORGE:SETTINGS_FIELDS` | (future) `Settings` dataclass | Per-feature settings |
| `FORGE:LIFECYCLE_STARTUP` / `FORGE:LIFECYCLE_SHUTDOWN` | (future) `AppLifecycle` | Startup/shutdown hooks |

## Adding a feature in seven steps

1. Decide `key`, display label, CLI flag, stability, and whether it's
   `always_on` or `default_enabled`.
2. Write the fragment directory at
   `forge/templates/_fragments/<key>/<language>/`. Start with `files/` for
   anything new and `inject.yaml` for modifications.
3. Register a `FeatureSpec` in `forge/features.py` via `register(...)`. Declare
   `depends_on`, `capabilities`, `conflicts_with` as needed.
4. If you introduce a new marker, add it to every base template that your
   feature supports *before* your fragment tries to use it.
5. If the feature brings new infrastructure (`redis`, a vector store...), add
   a `capabilities` entry and wire the capability string into
   `forge/docker_manager.py`'s compose renderer.
6. Write tests: at minimum, a unit test for any new logic plus one end-to-end
   apply-to-stub test (see `tests/test_feature_injector.py` —
   `test_correlation_id_fragment_end_to_end` as a pattern).
7. Document the feature: add a row to this file's feature list and a short
   blurb in the project `README.md`.

## User config

End users can enable features either in a YAML config:

```yaml
features:
  rate_limit:
    enabled: true
    options:
      requests_per_minute: 120
  agent:
    enabled: true
    options:
      provider: anthropic
      default_model: claude-opus-4-7-1m
```

…or via repeatable CLI flags:

```bash
forge --enable-feature rate_limit --enable-feature agent --yes --no-docker \
      --project-name My-App --backend-language python --frontend vue
```

CLI flags override YAML. Sub-flag-shaped options (e.g. vector store choice)
live under `options:` in YAML; a future release will expose them as top-level
CLI flags via `FeatureSpec.extra_flags`.

## Currently registered features

| Key | Stability | Default | Scope | Backends | Purpose |
|---|---|---|---|---|---|
| `correlation_id` | stable | always-on | backend | python | X-Request-ID middleware |
| `rate_limit` | stable | on | backend | python, node, rust | Token-bucket rate limiter (Py in-memory / `@fastify/rate-limit` / Axum tower middleware) |
| `security_headers` | stable | on | backend | python, node, rust | CSP / XFO / HSTS response headers |
| `pii_redaction` | stable | on | backend | python | Logging filter that scrubs emails, tokens, and API keys |
| `observability` | stable | off | backend | python, node, rust | Logfire (Py) / OpenTelemetry SDK (Node) / OTLP gRPC via tracing-opentelemetry (Rust) |
| `response_cache` | beta | off | backend | python, node | fastapi-cache2 + Redis (Py) / @fastify/caching (Node) |
| `background_tasks` | beta | off | backend | python, node, rust | Taskiq (Py) / BullMQ + ioredis (Node) / Apalis + Redis (Rust) |
| `enhanced_health` | beta | off | backend | python, node, rust | /api/v1/health/deep aggregates Redis + Keycloak checks |
| `conversation_persistence` | beta | off | backend | python | SQLAlchemy Conversation/Message/ToolCall + Alembic migration 0002 |
| `agent_tools` | experimental | off | backend | python | Tool base class + registry + pre-baked tools + /api/v1/tools endpoint |
| `agent_streaming` | experimental | off | backend | python | /api/v1/ws/agent WebSocket with typed event protocol + runner dispatch |
| `agent` | experimental | off | backend | python | pydantic-ai LLM loop (Anthropic/OpenAI/Google/OpenRouter), real streaming via agent.iter() |
| `file_upload` | beta | off | backend | python | /api/v1/chat-files endpoint + ChatFile model + local storage |
| `rag_pipeline` | experimental | off | backend | python | OpenAI embeddings + pgvector + /api/v1/rag ingest/search (text + PDF) + rag_search tool |
| `rag_postgresql` | experimental | off | backend | python | Plain-PostgreSQL (no pgvector extension) alternative, /api/v1/rag/pg/*, JSONB embeddings + Python-side cosine |
| `rag_qdrant` | experimental | off | backend | python | Qdrant vector-store alternative, /api/v1/rag/qdrant/* endpoints alongside pgvector |
| `rag_chroma` | experimental | off | backend | python | Chroma vector-store alternative, /api/v1/rag/chroma/* |
| `rag_milvus` | experimental | off | backend | python | Milvus vector-store alternative, /api/v1/rag/milvus/*, HNSW + COSINE, Zilliz Cloud compatible |
| `rag_weaviate` | experimental | off | backend | python | Weaviate v4 vector-store alternative, /api/v1/rag/weaviate/*, async HNSW + COSINE |
| `rag_pinecone` | experimental | off | backend | python | Pinecone (managed) vector-store, /api/v1/rag/pinecone/*, namespace-per-tenant isolation |
| `rag_reranking` | experimental | off | backend | python | Cohere rerank (default) + local cross-encoder fallback, /api/v1/rag/rerank/search |
| `rag_embeddings_voyage` | experimental | off | backend | python | Voyage AI embeddings as a drop-in replacement for the OpenAI embed module |
| `rag_sync_tasks` | experimental | off | backend | python | Taskiq tasks for async RAG ingestion (requires background_tasks) |
| `admin_panel` | beta | off | backend | python | SQLAdmin at /admin, env-gated, auto-registers views for shipped models |
| `webhooks` | beta | off | backend | python, node, rust | /api/v1/webhooks CRUD + HMAC-signed outbound delivery (Py: migration 0005; Node/Rust: in-memory v1) |
| `cli_commands` | beta | off | backend | python | `app info` / `app tools` / `app rag` typer subcommands on the existing CLI |
| `agents_md` | stable | on | project | any | Drops AGENTS.md + CLAUDE.md at project root |

Run `forge --list-features` for the up-to-date list.

## Fragment scopes

A feature's `FragmentImplSpec.scope` decides where its fragment is applied:

- **`backend`** (default) — applied once per supporting backend directory.
  Use for per-service middleware, route additions, dependency edits.
- **`project`** — applied once to the project root after all backends are
  generated. Use for cross-cutting files (AGENTS.md, shared Makefile,
  root-level CI workflows). Registered under every backend key but emits a
  single time.

## Roadmap — not yet implemented

These tiers from the plan aren't in the registry yet. When added, they will
follow the same `FeatureSpec` shape; configuration will be additive (users of
earlier forge versions see no behavior change). Tracked in
[ROADMAP](../README.md) of the generator repo.

### Tier 2 (opt-in ops essentials)

Shipped:

- **`rate_limit`** — Python (in-memory token bucket, previously always-on in
  the base template), Node (`@fastify/rate-limit`), and Rust (per-IP token
  bucket via `axum::middleware::from_fn`). All `default_enabled=True`.
- **`observability`** — Python Logfire, Node OpenTelemetry SDK
  (auto-instrumentations for Fastify / HTTP / pg, OTLP HTTP exporter,
  graceful no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` unset), Rust scaffold
  (layered `tracing_subscriber::registry` + `telemetry::build_otel_layer`
  stub — add `opentelemetry-otlp` with your transport feature to complete).
- **`response_cache`** — Python (fastapi-cache2 + Redis) and Node
  (@fastify/caching).
- **`background_tasks`** — Python (Taskiq broker + example task; run via
  `uv run taskiq worker`) and Node (BullMQ queue + worker script).
- **`enhanced_health`** — Python + Node + Rust. Mounts
  `/api/v1/health/deep` that aggregates Redis + Keycloak readiness checks
  on top of the base router's DB check. Missing deps (`redis`, `httpx`)
  return DOWN rather than crashing. Rust variant uses a TCP-reachability
  probe for Redis (no `redis` crate dep) and reqwest for Keycloak.

Not yet shipped:

- **`response_cache/rust`** — no clear canonical library yet; roll your own
  with `moka` + a tower `Layer`.
- **`background_tasks/rust`** — tokio task runner with a Redis-backed queue
  (Faktory-style or custom).

### Tier 3 (AI agent platform)

Python-only in v1 (pydantic-ai); Node and Rust will arrive later if demand
materializes.

Shipped:

- **`agent_tools`** — `Tool` base class, process-wide `ToolRegistry`, pre-baked
  `current_datetime` + `web_search` (Tavily, gracefully disabled without key).
  /api/v1/tools endpoint lists and invokes registered tools.
  `stability="experimental"` until a full agent loop is wired.
- **`conversation_persistence`** — `Conversation`, `Message`, `ToolCall`
  SQLAlchemy models + Pydantic domain schemas + `ConversationRepository`
  + Alembic migration `0002`. Pure-files fragment; `stability="beta"` until
  dependency-injection wiring lands. Per-tenant, per-user scoped.
- **`agent_streaming`** — `/api/v1/ws/agent` WebSocket with a typed event
  protocol (`ConversationCreated`, `UserPromptReceived`, `TextDelta`,
  `ToolCallStarted`, `ToolResult`, `AgentStatus`, `ErrorEvent`) + echo
  runner + runner dispatch module. Prompt starting with `/tool <name>`
  dispatches to the `agent_tools` registry for a real tool-call round-trip.
  `stability="experimental"`; depends on `conversation_persistence`.
- **`agent`** — pydantic-ai LLM loop that drops in as a replacement for
  the echo runner (via `app.agents.runner` dispatch). Provider selected
  from `LLM_PROVIDER` env: `anthropic` (default), `openai`, `google`, or
  `openrouter`. Tools registered in the `agent_tools` registry are bridged
  into pydantic-ai automatically. Graceful error event on missing API key.
  Real per-delta streaming via `agent.iter()` with automatic fallback to
  chunked `agent.run()` output if the installed pydantic-ai lacks the
  required event classes. `stability="experimental"`; depends on
  `agent_streaming` + `agent_tools`.
- **`file_upload`** — `/api/v1/chat-files` endpoint with multipart upload,
  MIME allowlist, size limit, path-traversal protection, and local-disk
  storage under `UPLOAD_DIR`. Ships a `ChatFile` SQLAlchemy model + Alembic
  migration `0003` (FK to `conversation_messages`) for users who want DB
  persistence; endpoint itself stays storage-only to avoid wiring Dishka
  DI. `stability="beta"`; depends on `conversation_persistence`.

Not yet shipped:

- (Tier 3 core complete.) Follow-ups include a DB-backed upload variant
  that writes the `ChatFile` row inline, S3 storage, and a RAG-style
  parsed-content pipeline that fills the `parsed_content` column.

### Tier 4 (RAG)

Shipped:

- **`rag_pipeline`** — OpenAI embeddings (`text-embedding-3-small` by
  default) + pgvector storage with an HNSW index (cosine distance) +
  recursive chunker (800-char / 120-char overlap) + retriever that
  enforces tenant isolation. `/api/v1/rag/ingest` accepts raw text and
  writes chunks transactionally; `/api/v1/rag/search` returns the top-k
  matches with their similarity scores. A `rag_search` tool auto-registers
  into the `agent_tools` registry when both features are enabled, so the
  LLM can call RAG without extra wiring. Migration `0004` creates the
  `vector` extension and the HNSW index. `stability="experimental"`;
  depends on `conversation_persistence`; adds the `postgres-pgvector`
  capability.

Also shipped:

- **`rag_postgresql`** — Plain-PostgreSQL backend for teams who can't
  install the `vector` extension (managed DBs, shared-tenant environments).
  Stores embeddings as JSONB arrays and scores cosine similarity
  Python-side after a candidate-limited fetch. Parallel
  `/api/v1/rag/pg/*` endpoints; migration 0006.
- **`rag_qdrant`** — Qdrant alternative to pgvector. Parallel
  `/api/v1/rag/qdrant/*` endpoints (ingest / ingest-pdf / search) that
  share the chunker + embeddings + pdf_parser from `rag_pipeline`.
- **`rag_chroma`** — Chroma backend via the async HTTP client. Parallel
  `/api/v1/rag/chroma/*` endpoints. Auto-creates the collection on first
  write.
- **`rag_reranking`** — Post-retrieval rerank pass. Cohere as default
  (`rerank-v3.5`), local sentence-transformers cross-encoder as fallback.
  Oversample factor 5 by default. Graceful no-op without provider config.
- **`rag_embeddings_voyage`** — Voyage AI provider drop-in for the embed
  module. Not wire-compatible with OpenAI (rebuild collections after
  switching). Defaults to `voyage-3.5` (1024-dim).
- **`rag_sync_tasks`** — Taskiq tasks (`ingest_text_task`,
  `ingest_pdf_bytes_task`) that move embed + store off the request
  thread. Requires `rag_pipeline` + `background_tasks`.
- **PDF ingestion** — `pymupdf` lands in `rag_pipeline`; a new
  `/api/v1/rag/ingest-pdf` multipart endpoint extracts text then runs the
  standard chunk + embed + store path. Scanned PDFs (no text layer)
  return 400 with an OCR hint rather than empty ingestion.

Not yet shipped:

- **Milvus / Weaviate / Pinecone vector stores** — same pattern as
  `rag_qdrant` / `rag_chroma`; straightforward ports when demand appears.
- **Alternative embeddings providers beyond OpenAI + Voyage** — Cohere
  embed, local `sentence-transformers`. Same pattern as
  `rag_embeddings_voyage`.

### Tier 5 (enterprise extras)

Shipped:

- **`admin_panel`** — Python. SQLAdmin UI at `/admin`. Env-gated via
  `ADMIN_PANEL_MODE` (`disabled` / `dev` / `all`); in `dev` the UI only
  mounts when `ENVIRONMENT` is `local` / `development`. Auto-registers
  `ModelView` for whichever tables the enabled features have shipped
  (items, audit_logs, conversations, webhooks, …) — missing imports are
  caught and skipped.
- **`webhooks`** — Python + Node. Python registry backed by SQLAlchemy
  model + migration 0005; Node registry is in-memory (swap for Prisma when
  multi-replica durability needed). Both ship HMAC-SHA256 signed delivery
  + `/test` endpoint. Synchronous best-effort; pair with
  `background_tasks` when retry queues are needed.
- **`cli_commands`** — Python. Extends the base template's typer CLI with
  `app info show`, `app tools list`, `app tools invoke`, `app rag ingest`.
  Each subcommand degrades gracefully if its prerequisite feature isn't
  present (prints a hint, exits non-zero).

Not yet shipped:

- **`webhooks/rust`** — axum endpoints + sqlx-backed registry + reqwest
  delivery. Medium effort; deferred.
- **`cli_commands/node`** — npm scripts already cover the equivalent
  surface (`npm run db:migrate`, etc.); explicit subcommands planned once
  a richer CLI framework like citty lands as a first-class dep.
- **`cli_commands/rust`** — clap-based subcommand layer layered on the
  existing `src/bin/migrate.rs` pattern.
- **`security_ratelimit_strict`** — composite preset bundling `rate_limit` +
  `security_headers` + tightened CORS.

## Design note — middleware ordering

`FeatureSpec.order` controls layering within a topological dependency tier.
Convention for Starlette/Axum-family middleware stacks where **later-added =
outer**:

- Assign numeric `order` ascending from *innermost* to *outermost*.
- Fragments use `position: before` on the `MIDDLEWARE_REGISTRATION` marker so
  earlier-resolved features land higher in the file (innermost) and
  later-resolved (higher `order`) features land just above the marker
  (outermost).

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
