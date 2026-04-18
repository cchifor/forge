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

Features are grouped by product category — the same order `forge --list-features`
prints and `--describe <key>` narrates. Run `forge --describe <key>` for the
full prose + tag lines (`BACKENDS:` / `ENDPOINTS:` / `REQUIRES:` /
`DEPENDS ON:`) per feature.

### Observability — visibility into the running system

| Name | Key | Stability | Default | Backends | Summary |
|---|---|---|---|---|---|
| Request Tracing | `correlation_id` | stable | always-on | python | X-Request-ID header + ContextVar propagation |
| Deep Health Checks | `enhanced_health` | beta | off | python, node, rust | /health aggregates DB + Redis + Keycloak readiness |
| Distributed Tracing | `observability` | stable | off | python, node, rust | Logfire (Py) / OTel SDK (Node) / OTLP gRPC via tracing-opentelemetry (Rust) |

Enable these when you need to trace a request hop across services, gate
rollouts on actual dependency health, or ship structured traces into an
OTLP collector.

### Reliability — protection + stability middleware

| Name | Key | Stability | Default | Backends | Summary |
|---|---|---|---|---|---|
| Rate Limiting | `rate_limit` | stable | on | python, node, rust | Token-bucket limiter keyed by tenant / IP |
| Security Headers | `security_headers` | stable | on | python, node, rust | CSP + XFO + HSTS + Referrer-Policy + Permissions-Policy |
| PII Scrubber | `pii_redaction` | stable | on | python | Logging.Filter that redacts emails / tokens / API keys |
| Response Cache | `response_cache` | beta | off | python, node | fastapi-cache2 + Redis (Py) / @fastify/caching (Node) |

The on-by-default entries are there for a reason; turn them off only for
intentional insecure-demo scenarios. Response cache is opt-in — decorate
specific handlers rather than blanket-enabling.

### Async Work — off-thread job processing

| Name | Key | Stability | Default | Backends | Summary |
|---|---|---|---|---|---|
| Task Queue | `background_tasks` | beta | off | python, node, rust | Taskiq (Py) / BullMQ + ioredis (Node) / Apalis + Redis (Rust) |
| Knowledge Ingest Queue | `rag_sync_tasks` | experimental | off | python | Taskiq tasks that move RAG ingest off the request thread |

Reach for these when you've got work a user shouldn't wait on —
emails, webhooks retries, RAG ingestion, LLM fan-outs. Node and Rust
variants share the `TASKIQ_BROKER_URL` env convention so docker-compose
ops stay uniform across backends.

### Conversational AI — chat, tools, and the agent loop

| Name | Key | Stability | Default | Backends | Summary |
|---|---|---|---|---|---|
| Chat History | `conversation_persistence` | beta | off | python | SQLAlchemy Conversation/Message/ToolCall + migration 0002 |
| Agent Stream | `agent_streaming` | experimental | off | python | /api/v1/ws/agent WebSocket with typed events + runner dispatch |
| Tool Registry | `agent_tools` | experimental | off | python | Tool base class + process registry + /api/v1/tools |
| LLM Agent | `agent` | experimental | off | python | pydantic-ai loop (Anthropic / OpenAI / Google / OpenRouter) |
| Chat Attachments | `file_upload` | beta | off | python | /api/v1/chat-files + ChatFile model + local storage |

Order of introduction: enable `conversation_persistence` first (storage),
then `agent_streaming` (WebSocket + echo runner), then `agent_tools` +
`agent` (LLM loop), then `file_upload` if you need attachments. The
`rag_search` agent tool auto-registers when RAG is also on, so the LLM
gets knowledge search with zero extra wiring.

### Knowledge — vector storage + retrieval (RAG)

| Name | Key | Stability | Default | Backends | Summary |
|---|---|---|---|---|---|
| Knowledge Search | `rag_pipeline` | experimental | off | python | OpenAI embeddings + pgvector + HNSW + PDF ingestion + `rag_search` tool |
| Knowledge Reranker | `rag_reranking` | experimental | off | python | Cohere + local cross-encoder fallback for sharper top-K |
| Knowledge — PostgreSQL | `rag_postgresql` | experimental | off | python | Plain-Postgres backend (no pgvector extension) |
| Knowledge — Qdrant | `rag_qdrant` | experimental | off | python | Qdrant alternative with parallel /api/v1/rag/qdrant/* endpoints |
| Knowledge — Chroma | `rag_chroma` | experimental | off | python | Chroma via AsyncHttpClient (container or Cloud) |
| Knowledge — Milvus | `rag_milvus` | experimental | off | python | AsyncMilvusClient, HNSW + COSINE, Zilliz-Cloud compatible |
| Knowledge — Weaviate | `rag_weaviate` | experimental | off | python | Weaviate v4 async backend with client-managed vectors |
| Knowledge — Pinecone | `rag_pinecone` | experimental | off | python | Managed Pinecone with namespace-per-tenant isolation |
| Knowledge — Voyage Embeddings | `rag_embeddings_voyage` | experimental | off | python | Drop-in embeddings provider (swap for OpenAI) |

`rag_pipeline` is the base — every alternative vector store depends on it
for the shared chunker, embeddings, and PDF parser, then adds its own
parallel `/api/v1/rag/<backend>/*` endpoints so multiple backends coexist
during a migration.

### Platform — operator-facing tooling

| Name | Key | Stability | Default | Backends | Summary |
|---|---|---|---|---|---|
| Admin Console | `admin_panel` | beta | off | python | SQLAdmin UI at /admin, env-gated, auto-registers views |
| Outbound Webhooks | `webhooks` | beta | off | python, node, rust | Registry + HMAC-SHA256 signed delivery + /test endpoint |
| Service CLI Extensions | `cli_commands` | beta | off | python | `app info` / `app tools` / `app rag` typer subcommands |
| AI Agent Handbook | `agents_md` | stable | on | all (project-scoped) | Drops AGENTS.md + CLAUDE.md at project root |

Operator UX — human admins browsing data, event fan-out for third-party
integrators, SSH-in shell commands, and guidance docs for AI coding
agents contributing to the generated repo.

Run `forge --list-features` for the up-to-date list, or
`forge --describe <key>` for the full prose + metadata of any single
feature.

## Fragment scopes

A feature's `FragmentImplSpec.scope` decides where its fragment is applied:

- **`backend`** (default) — applied once per supporting backend directory.
  Use for per-service middleware, route additions, dependency edits.
- **`project`** — applied once to the project root after all backends are
  generated. Use for cross-cutting files (AGENTS.md, shared Makefile,
  root-level CI workflows). Registered under every backend key but emits a
  single time.

## Roadmap — not yet shipped

These backends/variants don't have a `FragmentImplSpec` yet. Configuration
will be purely additive when they land, so existing projects see no
behavior change.

- **`response_cache/rust`** — no clear canonical library yet; roll your own
  with `moka` + a tower `Layer`.
- **`webhooks/rust` durable registry** — axum + sqlx-backed persistence.
  (In-memory v1 is already shipped — this is the durability upgrade.)
- **`cli_commands/node`** — npm scripts already cover the surface; explicit
  subcommands planned once a CLI framework like `citty` lands as a first-
  class dep.
- **`cli_commands/rust`** — clap-based subcommand layer on top of the
  existing `src/bin/migrate.rs` pattern.
- **Additional embeddings providers** beyond OpenAI + Voyage — Cohere
  embed, local `sentence-transformers`. Same pattern as
  `rag_embeddings_voyage`.
- **`security_ratelimit_strict`** — composite preset bundling
  `rate_limit` + `security_headers` + tightened CORS.

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
