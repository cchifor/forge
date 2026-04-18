"""Feature registry for forge.

Parallel to `BACKEND_REGISTRY` in `forge/config.py`. Every opt-in or always-on
capability beyond the bare CRUD scaffold — middleware, observability, agent
platform, RAG — is a `FeatureSpec` entry here. The registry is the single
source of truth: `cli.py`, `generator.py`, `docker_manager.py`, and the
feature_injector all read from it, never hardcode feature logic.

Feature implementations live in `forge/templates/_fragments/<feature_key>/<backend_lang>/`
and are applied by `feature_injector.apply_features` after each backend is
rendered by Copier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from forge.config import BackendLanguage

# Marker format used to locate injection points in base templates.
# Python/Rust/TS source files use `# FORGE:NAME` / `// FORGE:NAME`.
# YAML uses `# FORGE:NAME`. Markers must be unique per file.
MARKER_PREFIX = "FORGE:"

# Root directory under forge/templates where all fragments live.
FRAGMENTS_DIRNAME = "_fragments"


Stability = Literal["stable", "beta", "experimental"]


@dataclass(frozen=True)
class FlagSpec:
    """A sub-flag of a feature — e.g. `--vector-store qdrant` for RAG."""

    cli_flag: str
    yaml_key: str
    choices: tuple[str, ...]
    default: str
    description: str = ""


FragmentScope = Literal["backend", "project"]


@dataclass(frozen=True)
class FragmentImplSpec:
    """Per-backend (or project-level) implementation of a feature.

    The fragment directory layout is:
        <feature_key>/<backend_lang>/
            inject.yaml   — list of (target, marker, snippet) injections
            files/        — verbatim files to copy into the generated project
            deps.yaml     — dependencies to add to pyproject/package.json/Cargo.toml
            env.yaml      — env vars to append to .env.example

    All four are optional; a fragment can be pure-injection, pure-files, or any mix.

    `scope="backend"` (default) applies to each supporting backend's directory.
    `scope="project"` applies once to the project root after all backends are
    generated — use for cross-cutting files like AGENTS.md or a shared Makefile.
    """

    fragment_dir: str  # relative to forge/templates/_fragments, e.g. "correlation_id/python"
    scope: FragmentScope = "backend"
    dependencies: tuple[str, ...] = ()
    env_vars: tuple[tuple[str, str], ...] = ()
    settings_keys: tuple[str, ...] = ()
    post_hooks: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureSpec:
    """Static metadata + per-backend implementations for one feature."""

    key: str
    display_label: str
    cli_flag: str  # `--include-<key>` by convention
    stability: Stability = "stable"
    default_enabled: bool = False
    always_on: bool = False  # True for migrated Tier 1 always-on middleware
    # Numeric ordering within topological layers. Lower = earlier apply. For
    # before-marker injections this lands the snippet further from the marker
    # (higher in the file) — use it to control middleware registration order
    # where outermost middleware must be added last. Default 100.
    order: int = 100
    implementations: dict[BackendLanguage, FragmentImplSpec] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()  # other feature keys
    conflicts_with: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()  # "redis", "qdrant", etc.
    extra_flags: tuple[FlagSpec, ...] = ()
    min_forge_version: str = "0.2.0"

    def supports(self, language: BackendLanguage) -> bool:
        return language in self.implementations


@dataclass
class FeatureConfig:
    """User-supplied state for a feature in a specific project.

    `enabled` always reflects the final decision (after defaults + always_on);
    `options` captures sub-flag values like `{"vector_store": "qdrant"}`.
    """

    enabled: bool = False
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Any) -> FeatureConfig:
        """Parse a YAML/JSON block. `True` / `False` shorthand is accepted."""
        if raw is True:
            return cls(enabled=True)
        if raw is False or raw is None:
            return cls(enabled=False)
        if not isinstance(raw, dict):
            raise ValueError(f"Feature config must be bool or dict, got {type(raw).__name__}")
        enabled = bool(raw.get("enabled", False))
        options = raw.get("options", {})
        if not isinstance(options, dict):
            raise ValueError(f"Feature options must be a dict, got {type(options).__name__}")
        return cls(enabled=enabled, options=dict(options))

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "options": dict(self.options)}


# The registry starts empty. Features are registered below as they're implemented.
FEATURE_REGISTRY: dict[str, FeatureSpec] = {}


def register(spec: FeatureSpec) -> None:
    """Register a feature. Raises if the key collides with an existing entry."""
    if spec.key in FEATURE_REGISTRY:
        raise ValueError(f"Feature '{spec.key}' is already registered.")
    FEATURE_REGISTRY[spec.key] = spec


def fragments_root() -> Path:
    """Filesystem path to the _fragments root under forge/templates/."""
    return Path(__file__).parent / "templates" / FRAGMENTS_DIRNAME


# -----------------------------------------------------------------------------
# Registered features
# -----------------------------------------------------------------------------

# correlation_id: extracts/generates an X-Request-ID header, binds it to a
# ContextVar, echoes it back, and stashes on request.state. Python base
# template currently ships this always-on; this registration preserves that
# behavior via a fragment so it can be observed by the feature system and,
# later, explicitly disabled for specialized deployments.
#
# order=90 is high so correlation_id's `app.add_middleware` call lands nearest
# to the MIDDLEWARE_REGISTRATION marker — i.e., is the LAST middleware added
# and therefore the OUTERMOST (sees every request first).
register(
    FeatureSpec(
        key="correlation_id",
        display_label="Correlation ID middleware",
        cli_flag="--include-correlation-id",
        stability="stable",
        default_enabled=True,
        always_on=True,
        order=90,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="correlation_id/python",
            ),
        },
    )
)


# security_headers: attaches CSP, X-Frame-Options, X-Content-Type-Options,
# Referrer-Policy, and HSTS to every response. Defaults ON — turning off
# is a deliberate choice for intentionally-insecure demos.
# rate_limit: tenant-/IP-keyed token-bucket rate limiter. Python ships an
# in-memory implementation; Node uses @fastify/rate-limit. Defaults ON for
# Python (preserves prior always-on behavior), OPT-IN for Node (new capability).
# order=50 places the registration between Audit (hardcoded) and the other
# fragments, matching the pre-fragment file layout.
register(
    FeatureSpec(
        key="rate_limit",
        display_label="Rate limiting middleware",
        cli_flag="--include-rate-limit",
        stability="stable",
        default_enabled=True,
        order=50,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rate_limit/python",
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="rate_limit/node",
                dependencies=("@fastify/rate-limit@10.3.0",),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="rate_limit/rust",
            ),
        },
    )
)


register(
    FeatureSpec(
        key="security_headers",
        display_label="Security headers middleware",
        cli_flag="--include-security-headers",
        stability="stable",
        default_enabled=True,
        order=80,  # below correlation_id (90) so it registers inside of it
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="security_headers/python",
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="security_headers/node",
                dependencies=("@fastify/helmet@13.0.1",),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="security_headers/rust",
            ),
        },
    )
)


# pii_redaction: a logging.Filter that scrubs emails, bearer tokens, and
# common API-key shapes from log records before they reach handlers.
# Attached at lifecycle startup, not as middleware.
register(
    FeatureSpec(
        key="pii_redaction",
        display_label="PII-redacting log filter",
        cli_flag="--include-pii-redaction",
        stability="stable",
        default_enabled=True,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="pii_redaction/python",
            ),
        },
    )
)


# observability: Logfire/OpenTelemetry auto-instrumentation for Python.
# Opt-in; most teams pair this with a LOGFIRE_TOKEN in their deployment secret.
# Missing dependency is a runtime warning, not a crash — so turning the feature
# on without pinning the dependency still produces a bootable service.
# enhanced_health: adds /api/v1/health/deep that aggregates Redis + Keycloak
# checks on top of the base router's db check. Best-effort — missing optional
# deps (redis, httpx) return DOWN rather than crashing the endpoint.
# admin_panel: SQLAdmin UI mounted at /admin. Env-gated exposure via
# ADMIN_PANEL_MODE (disabled / dev / all). Auto-registers ModelViews for
# whatever tables the enabled features have shipped (items, audit_logs,
# conversations, webhooks, …) — missing imports are caught and skipped.
register(
    FeatureSpec(
        key="admin_panel",
        display_label="SQLAdmin UI at /admin",
        cli_flag="--include-admin-panel",
        stability="beta",
        default_enabled=False,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="admin_panel/python",
                dependencies=("sqladmin>=0.20.0", "itsdangerous>=2.2.0"),
                env_vars=(("ADMIN_PANEL_MODE", "dev"),),
            ),
        },
    )
)


# webhooks: registry + HMAC-SHA256 signed outbound delivery. v1 is
# synchronous best-effort; pair with background_tasks to get retry
# semantics. Ships migration 0005 for the `webhooks` table.
register(
    FeatureSpec(
        key="webhooks",
        display_label="Outbound HTTP webhooks",
        cli_flag="--include-webhooks",
        stability="beta",
        default_enabled=False,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="webhooks/python",
                dependencies=("httpx>=0.28.0",),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="webhooks/node",
                # In-memory registry in v1 — no extra deps; Node's crypto +
                # global fetch cover HMAC + delivery.
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="webhooks/rust",
                # hex encoding is hand-rolled; hmac + sha2 carry the crypto;
                # reqwest is already in the base Cargo.toml.
                dependencies=(
                    "hmac@0.12",
                    "sha2@0.10",
                ),
            ),
        },
    )
)


# cli_commands: extends the base template's `app` typer CLI with
# info/tools/rag subcommands. Each subcommand degrades gracefully if its
# prerequisite feature (agent_tools / rag_pipeline) isn't enabled — the
# command prints a hint and exits non-zero rather than import-crashing.
register(
    FeatureSpec(
        key="cli_commands",
        display_label="Extended CLI subcommands (info/tools/rag)",
        cli_flag="--include-cli-commands",
        stability="beta",
        default_enabled=False,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="cli_commands/python",
            ),
        },
    )
)


# conversation_persistence: SQLAlchemy models + Pydantic schemas + repository
# + Alembic migration for conversations, messages, and tool calls. Pure-files
# fragment — no injections into the base template. agent_streaming uses this
# to persist chat history.
register(
    FeatureSpec(
        key="conversation_persistence",
        display_label="Conversation / Message / ToolCall persistence",
        cli_flag="--include-conversation-persistence",
        stability="beta",
        default_enabled=False,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="conversation_persistence/python",
            ),
        },
    )
)


# agent_streaming: WebSocket endpoint at /api/v1/ws/agent that streams typed
# AgentEvent JSON frames. Ships with an echo runner and a dispatch module
# (runner.py) that prefers app.agents.llm_runner if present — so adding
# the `agent` feature swaps in a real LLM loop with zero endpoint churn.
register(
    FeatureSpec(
        key="agent_streaming",
        display_label="Agent streaming WebSocket (/ws/agent)",
        cli_flag="--include-agent-streaming",
        stability="experimental",
        default_enabled=False,
        depends_on=("conversation_persistence",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="agent_streaming/python",
            ),
        },
    )
)


# response_cache: fastapi-cache2 wired with a Redis backend (falls back to
# in-memory when REDIS_URL missing/unreachable). Route handlers opt in per-
# endpoint via the @cache decorator; no blanket behavior change.
register(
    FeatureSpec(
        key="response_cache",
        display_label="Response cache (fastapi-cache2 / @fastify/caching)",
        cli_flag="--include-response-cache",
        stability="beta",
        default_enabled=False,
        capabilities=("redis",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="response_cache/python",
                dependencies=("fastapi-cache2>=0.2.2", "redis>=6.0.0"),
                env_vars=(
                    ("RESPONSE_CACHE_URL", "redis://redis:6379/1"),
                    ("RESPONSE_CACHE_PREFIX", "forge:cache"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="response_cache/node",
                dependencies=("@fastify/caching@9.0.1",),
                env_vars=(("RESPONSE_CACHE_URL", "redis://redis:6379/1"),),
            ),
        },
    )
)


# background_tasks: Taskiq broker + result backend on Redis. Users define
# tasks in app/worker/tasks.py and run the worker via `taskiq worker`.
register(
    FeatureSpec(
        key="background_tasks",
        display_label="Background task queue (Taskiq / BullMQ)",
        cli_flag="--include-background-tasks",
        stability="beta",
        default_enabled=False,
        capabilities=("redis",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="background_tasks/python",
                dependencies=("taskiq>=0.11.0", "taskiq-redis>=1.0.0"),
                env_vars=(
                    ("TASKIQ_BROKER_URL", "redis://redis:6379/2"),
                    ("TASKIQ_RESULT_BACKEND_URL", "redis://redis:6379/2"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="background_tasks/node",
                dependencies=("bullmq@5.30.0", "ioredis@5.4.1"),
                env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="background_tasks/rust",
                dependencies=(
                    "apalis@0.6",
                    "apalis-redis@0.6",
                ),
                env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
            ),
        },
    )
)


# rag_pipeline: OpenAI embeddings + pgvector storage + retriever + ingest/
# search REST endpoints + a rag_search tool that auto-registers into the
# ToolRegistry (when agent_tools is enabled). Ships migration 0004 which
# adds the pgvector extension — run alembic upgrade head before first use.
register(
    FeatureSpec(
        key="rag_pipeline",
        display_label="RAG pipeline (pgvector + OpenAI embeddings)",
        cli_flag="--include-rag",
        stability="experimental",
        default_enabled=False,
        depends_on=("conversation_persistence",),
        capabilities=("postgres-pgvector",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_pipeline/python",
                dependencies=(
                    "pgvector>=0.3.0",
                    "openai>=2.0.0",
                    "pymupdf>=1.24.0",
                    "python-multipart>=0.0.20",
                ),
                env_vars=(
                    ("EMBEDDING_MODEL", "text-embedding-3-small"),
                    ("EMBEDDING_DIM", "1536"),
                    ("RAG_TOP_K", "5"),
                    ("OPENAI_BASE_URL", ""),
                ),
            ),
        },
    )
)


# rag_sync_tasks: Taskiq tasks that move RAG ingestion off the request
# thread. Depends on both rag_pipeline (for chunker/embeddings/store) and
# background_tasks (for the broker). Enqueue with
# ``await ingest_text_task.kiq(...)`` from any handler.
register(
    FeatureSpec(
        key="rag_sync_tasks",
        display_label="Async RAG ingestion tasks (Taskiq)",
        cli_flag="--include-rag-sync-tasks",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline", "background_tasks"),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_sync_tasks/python",
            ),
        },
    )
)


# rag_embeddings_voyage: Voyage AI as an alternative embeddings provider.
# Ships a drop-in module; users change one import to swap from OpenAI.
# **Not interoperable** with OpenAI embeddings — rebuild any existing
# vector collection after switching (different provider = different space).
register(
    FeatureSpec(
        key="rag_embeddings_voyage",
        display_label="RAG Voyage AI embeddings provider",
        cli_flag="--include-rag-voyage",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_embeddings_voyage/python",
                dependencies=("voyageai>=0.3.0",),
                env_vars=(
                    ("VOYAGE_API_KEY", ""),
                    ("EMBEDDING_MODEL", "voyage-3.5"),
                    ("EMBEDDING_DIM", "1024"),
                ),
            ),
        },
    )
)


# rag_reranking: post-retrieval rerank pass (Cohere default, local
# sentence-transformers cross-encoder as an opt-in fallback). Ships a
# reranker module + /api/v1/rag/rerank/search endpoint that oversamples
# candidates via the pgvector retriever and reorders with rerank scores.
# Graceful no-op when no provider is configured.
register(
    FeatureSpec(
        key="rag_reranking",
        display_label="RAG reranking (Cohere / local cross-encoder)",
        cli_flag="--include-rag-reranking",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_reranking/python",
                dependencies=("cohere>=5.13.0",),
                env_vars=(
                    ("COHERE_API_KEY", ""),
                    ("RERANKER_PROVIDER", "cohere"),
                    ("RERANKER_MODEL", ""),
                ),
            ),
        },
    )
)


# rag_milvus: Milvus backend using AsyncMilvusClient. HNSW + COSINE by
# default. Supports both self-hosted Milvus and Zilliz Cloud via MILVUS_URI
# / MILVUS_TOKEN. Parallel /api/v1/rag/milvus/* endpoints.
register(
    FeatureSpec(
        key="rag_milvus",
        display_label="RAG Milvus backend",
        cli_flag="--include-rag-milvus",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("milvus",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_milvus/python",
                dependencies=("pymilvus>=2.5.0",),
                env_vars=(
                    ("MILVUS_URI", "http://milvus:19530"),
                    ("MILVUS_TOKEN", ""),
                    ("MILVUS_COLLECTION", "forge_rag"),
                ),
            ),
        },
    )
)


# rag_weaviate: Weaviate v4 async backend. Uses Weaviate's HNSW + cosine
# with server-side vector management disabled (we ship our own embeddings).
# Parallel /api/v1/rag/weaviate/* endpoints.
register(
    FeatureSpec(
        key="rag_weaviate",
        display_label="RAG Weaviate backend",
        cli_flag="--include-rag-weaviate",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("weaviate",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_weaviate/python",
                dependencies=("weaviate-client>=4.9.0",),
                env_vars=(
                    ("WEAVIATE_URL", "http://weaviate:8080"),
                    ("WEAVIATE_API_KEY", ""),
                    ("WEAVIATE_COLLECTION", "ForgeRag"),
                ),
            ),
        },
    )
)


# rag_pinecone: Managed Pinecone backend. Namespace-per-tenant for hard
# isolation. Index must be pre-created (Pinecone doesn't auto-create).
# Parallel /api/v1/rag/pinecone/* endpoints.
register(
    FeatureSpec(
        key="rag_pinecone",
        display_label="RAG Pinecone backend",
        cli_flag="--include-rag-pinecone",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("pinecone",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_pinecone/python",
                dependencies=("pinecone>=5.4.0",),
                env_vars=(
                    ("PINECONE_API_KEY", ""),
                    ("PINECONE_INDEX", "forge-rag"),
                    ("PINECONE_ENVIRONMENT", ""),
                ),
            ),
        },
    )
)


# rag_chroma: Chroma vector-store alternative. Parallel /api/v1/rag/chroma/*
# endpoints sharing chunker + embeddings + pdf_parser with rag_pipeline.
# Uses the AsyncHttpClient so a Chroma server container or Chroma Cloud
# endpoint are swappable via CHROMA_URL.
register(
    FeatureSpec(
        key="rag_chroma",
        display_label="RAG Chroma backend",
        cli_flag="--include-rag-chroma",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("chroma",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_chroma/python",
                dependencies=("chromadb>=0.5.0",),
                env_vars=(
                    ("CHROMA_URL", "http://chroma:8000"),
                    ("CHROMA_COLLECTION", "forge_rag"),
                    ("CHROMA_TENANT", "default_tenant"),
                    ("CHROMA_DATABASE", "default_database"),
                ),
            ),
        },
    )
)


# rag_postgresql: plain-PostgreSQL alternative for managed DB environments
# that can't install the pgvector extension. Stores embeddings as JSONB,
# computes cosine similarity Python-side post-fetch. Slower than pgvector
# at scale but portable. Migration 0006 adds the chunks table.
register(
    FeatureSpec(
        key="rag_postgresql",
        display_label="RAG plain-PostgreSQL backend (no pgvector)",
        cli_flag="--include-rag-postgresql",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_postgresql/python",
            ),
        },
    )
)


# rag_qdrant: Qdrant vector-store alternative to pgvector. Adds parallel
# /api/v1/rag/qdrant/* endpoints without touching the pgvector ones, so
# users can migrate incrementally. Depends on rag_pipeline for the shared
# embeddings + chunker + pdf_parser modules.
register(
    FeatureSpec(
        key="rag_qdrant",
        display_label="RAG Qdrant backend",
        cli_flag="--include-rag-qdrant",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("qdrant",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_qdrant/python",
                dependencies=("qdrant-client>=1.12.0",),
                env_vars=(
                    ("QDRANT_URL", "http://qdrant:6333"),
                    ("QDRANT_API_KEY", ""),
                    ("QDRANT_COLLECTION", "forge_rag"),
                ),
            ),
        },
    )
)


# file_upload: multipart upload + download endpoints under /api/v1/chat-files,
# local-disk storage (UPLOAD_DIR) with size + MIME validation, and a ChatFile
# SQLAlchemy model + migration for users who want DB persistence. The
# endpoint itself is storage-only (no DB write) so dropping it in doesn't
# require Dishka DI changes; wire the model into your repo layer as needed.
register(
    FeatureSpec(
        key="file_upload",
        display_label="Chat file upload (local storage + ChatFile model)",
        cli_flag="--include-file-upload",
        stability="beta",
        default_enabled=False,
        depends_on=("conversation_persistence",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="file_upload/python",
                dependencies=("python-multipart>=0.0.20",),
                env_vars=(
                    ("UPLOAD_DIR", "./uploads"),
                    ("MAX_UPLOAD_SIZE", "10485760"),
                    ("ALLOWED_MIME_TYPES", ""),
                ),
            ),
        },
    )
)


# agent: pydantic-ai LLM loop that swaps in for the echo runner shipped by
# agent_streaming. Auto-picks provider from LLM_PROVIDER env (anthropic /
# openai / google / openrouter). Tools registered with agent_tools get
# bridged into pydantic-ai automatically. A missing API key produces a
# clean error event rather than a crash.
register(
    FeatureSpec(
        key="agent",
        display_label="LLM agent loop (pydantic-ai)",
        cli_flag="--include-agent",
        stability="experimental",
        default_enabled=False,
        depends_on=("agent_streaming", "agent_tools"),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="agent/python",
                dependencies=("pydantic-ai>=0.0.14",),
                env_vars=(
                    ("LLM_PROVIDER", "anthropic"),
                    ("LLM_MODEL", ""),
                    ("ANTHROPIC_API_KEY", ""),
                    ("OPENAI_API_KEY", ""),
                    ("GOOGLE_API_KEY", ""),
                    ("OPENROUTER_API_KEY", ""),
                    ("AGENT_SYSTEM_PROMPT", ""),
                ),
            ),
        },
    )
)


# agent_tools: lightweight Tool base class + process-wide registry + two
# pre-baked tools (current_datetime, web_search). Skeleton for a future
# `agent` feature (pydantic-ai wiring, WebSocket streaming). Today it ships
# the scaffolding and a /api/v1/tools list+invoke endpoint so users can
# exercise tools without an LLM loop.
register(
    FeatureSpec(
        key="agent_tools",
        display_label="Agent tool registry + pre-baked tools",
        cli_flag="--include-agent-tools",
        stability="experimental",
        default_enabled=False,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="agent_tools/python",
                dependencies=("httpx>=0.28.0",),
                env_vars=(("TAVILY_API_KEY", ""),),
            ),
        },
    )
)


register(
    FeatureSpec(
        key="enhanced_health",
        display_label="Deep readiness endpoint (Redis + Keycloak)",
        cli_flag="--include-enhanced-health",
        stability="beta",
        default_enabled=False,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="enhanced_health/python",
                dependencies=("redis>=6.0.0",),
                env_vars=(
                    ("REDIS_URL", "redis://redis:6379/0"),
                    ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="enhanced_health/node",
                dependencies=("redis@4.7.0",),
                env_vars=(
                    ("REDIS_URL", "redis://redis:6379/0"),
                    ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                ),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="enhanced_health/rust",
                env_vars=(
                    ("REDIS_URL", "redis://redis:6379/0"),
                    ("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready"),
                ),
            ),
        },
    )
)


register(
    FeatureSpec(
        key="observability",
        display_label="OpenTelemetry / Logfire instrumentation",
        cli_flag="--include-observability",
        stability="stable",
        default_enabled=False,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="observability/python",
                dependencies=("logfire>=3.0.0",),
                env_vars=(
                    ("LOGFIRE_TOKEN", ""),
                    ("LOGFIRE_SERVICE_NAME", "forge-service"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="observability/node",
                dependencies=(
                    "@opentelemetry/sdk-node@0.55.0",
                    "@opentelemetry/auto-instrumentations-node@0.55.0",
                    "@opentelemetry/exporter-trace-otlp-http@0.55.0",
                    "@opentelemetry/resources@1.29.0",
                    "@opentelemetry/semantic-conventions@1.29.0",
                ),
                env_vars=(
                    ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                    ("OTEL_SERVICE_NAME", "forge-service"),
                    ("OTEL_SERVICE_VERSION", "0.1.0"),
                ),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="observability/rust",
                dependencies=(
                    "opentelemetry@0.27",
                    'opentelemetry_sdk = { version = "0.27", features = ["rt-tokio"] }',
                    'opentelemetry-otlp = { version = "0.27", features = ["grpc-tonic"] }',
                    "tracing-opentelemetry@0.28",
                ),
                env_vars=(
                    ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                    ("OTEL_SERVICE_NAME", "forge-service"),
                ),
            ),
        },
    )
)


# agents_md: drops AGENTS.md + CLAUDE.md at the project root so AI coding
# agents (Claude Code, Cursor, Copilot workspaces) can orient themselves
# before touching generated code. Project-scoped: emitted once regardless
# of how many backends the project has.
_AGENTS_MD_IMPL = FragmentImplSpec(fragment_dir="agents_md/all", scope="project")
register(
    FeatureSpec(
        key="agents_md",
        display_label="AGENTS.md + CLAUDE.md at project root",
        cli_flag="--include-agents-md",
        stability="stable",
        default_enabled=True,
        implementations={
            BackendLanguage.PYTHON: _AGENTS_MD_IMPL,
            BackendLanguage.NODE: _AGENTS_MD_IMPL,
            BackendLanguage.RUST: _AGENTS_MD_IMPL,
        },
    )
)
