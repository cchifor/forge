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
from enum import Enum
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


class FeatureCategory(Enum):
    """Product-level grouping for the feature catalogue.

    Categories describe *what customers are trying to do*, not how the
    feature is implemented. `forge --list-features` prints features in
    this order; docs/FEATURES.md groups them the same way.
    """

    OBSERVABILITY = "observability"
    RELIABILITY = "reliability"
    ASYNC_WORK = "async-work"
    CONVERSATIONAL_AI = "conversational-ai"
    KNOWLEDGE = "knowledge"
    PLATFORM = "platform"


CATEGORY_ORDER: tuple[FeatureCategory, ...] = (
    FeatureCategory.OBSERVABILITY,
    FeatureCategory.RELIABILITY,
    FeatureCategory.ASYNC_WORK,
    FeatureCategory.CONVERSATIONAL_AI,
    FeatureCategory.KNOWLEDGE,
    FeatureCategory.PLATFORM,
)

CATEGORY_DISPLAY: dict[FeatureCategory, str] = {
    FeatureCategory.OBSERVABILITY: "Observability",
    FeatureCategory.RELIABILITY: "Reliability",
    FeatureCategory.ASYNC_WORK: "Async Work",
    FeatureCategory.CONVERSATIONAL_AI: "Conversational AI",
    FeatureCategory.KNOWLEDGE: "Knowledge",
    FeatureCategory.PLATFORM: "Platform",
}

CATEGORY_MISSION: dict[FeatureCategory, str] = {
    FeatureCategory.OBSERVABILITY: "Visibility into the running system — tracing, metrics, health.",
    FeatureCategory.RELIABILITY: "Protection + stability middleware that every production service needs.",
    FeatureCategory.ASYNC_WORK: "Off-thread job processing so request handlers stay fast.",
    FeatureCategory.CONVERSATIONAL_AI: "Chat persistence, tool registry, streaming WebSocket, and an LLM agent loop.",
    FeatureCategory.KNOWLEDGE: "Vector storage and retrieval — the RAG stack with pluggable backends.",
    FeatureCategory.PLATFORM: "Operator-facing tooling: admin UI, outbound webhooks, CLI extensions, AI-agent docs.",
}


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
    # Product-level grouping. Drives --list-features output order and the
    # section layout in docs/FEATURES.md.
    category: FeatureCategory = FeatureCategory.PLATFORM
    # Rich description targeting both humans (prose paragraph) and agents
    # (structured `BACKENDS:` / `ENDPOINTS:` / `REQUIRES:` / `DEPENDS ON:`
    # tag lines they can parse with a regex). Printed by `forge --describe`.
    description: str = ""

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

register(
    FeatureSpec(
        key="correlation_id",
        display_label="Request Tracing",
        cli_flag="--include-correlation-id",
        stability="stable",
        default_enabled=True,
        always_on=True,
        order=90,
        category=FeatureCategory.OBSERVABILITY,
        description="""\
Every inbound request is tagged with an X-Request-ID header, the value is
stored in a ContextVar so any async task downstream sees it, and the same
ID is echoed back on the response. Index the `correlation_id` log field
in your aggregator to trace a single request end-to-end across services.

WHEN TO ENABLE: always-on — cannot be disabled.
BACKENDS: python
ENDPOINTS: none — ambient context via service.observability.correlation
REQUIRES: nothing
DEPENDS ON: —""",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="correlation_id/python",
            ),
        },
    )
)


register(
    FeatureSpec(
        key="rate_limit",
        display_label="Rate Limiting",
        cli_flag="--include-rate-limit",
        stability="stable",
        default_enabled=True,
        order=50,
        category=FeatureCategory.RELIABILITY,
        description="""\
Token-bucket rate limiter, keyed by tenant when authenticated or by client
IP otherwise. Protects downstream services from hot callers and smooths
burst traffic. Ships three first-class implementations with matching knobs
— Python (in-memory), Node (@fastify/rate-limit), Rust (Axum tower layer).

WHEN TO ENABLE: public-facing APIs, or anywhere you need fair-share traffic shaping.
BACKENDS: python, node, rust
ENDPOINTS: returns 429 on limit breach; /health and /metrics are skipped.
REQUIRES: nothing by default; set REDIS_URL to share state across replicas.
DEPENDS ON: —""",
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
        display_label="Security Headers",
        cli_flag="--include-security-headers",
        stability="stable",
        default_enabled=True,
        order=80,  # below correlation_id (90) so it registers inside of it
        category=FeatureCategory.RELIABILITY,
        description="""\
Attaches a conservative set of response headers (CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy, and HSTS on
HTTPS responses) to every request. Turning this off is a deliberate choice
for intentionally-insecure demos.

WHEN TO ENABLE: any service serving browsers; leave on by default.
BACKENDS: python, node, rust
ENDPOINTS: none — middleware decorates every response.
REQUIRES: nothing
DEPENDS ON: —""",
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


register(
    FeatureSpec(
        key="pii_redaction",
        display_label="PII Scrubber",
        cli_flag="--include-pii-redaction",
        stability="stable",
        default_enabled=True,
        category=FeatureCategory.RELIABILITY,
        description="""\
A logging.Filter attached at startup that scrubs emails, bearer tokens,
common API-key shapes (sk-*, sk-ant-*, AIza*, hf_*), and
password=/api_key= value pairs from every log record before handlers run.
Helps satisfy GDPR / SOC2 log-hygiene requirements without per-call-site
discipline.

WHEN TO ENABLE: any service logging request payloads or third-party responses.
BACKENDS: python
ENDPOINTS: none — applies to logger output globally.
REQUIRES: nothing
DEPENDS ON: —""",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="pii_redaction/python",
            ),
        },
    )
)


register(
    FeatureSpec(
        key="admin_panel",
        display_label="Admin Console",
        cli_flag="--include-admin-panel",
        stability="beta",
        default_enabled=False,
        category=FeatureCategory.PLATFORM,
        description="""\
A browser-facing admin UI mounted at /admin, built on SQLAdmin. It
auto-registers ModelViews for whichever tables the enabled features have
shipped — items, audit_logs, conversations, messages, webhooks — and
skips any model whose Python import fails, so mix-and-match feature
combinations render a clean UI rather than a 500.

WHEN TO ENABLE: dev environments or internal admins. Keep off in production
unless you also wrap it with your auth proxy.
BACKENDS: python
ENDPOINTS: /admin (HTML UI)
REQUIRES: ADMIN_PANEL_MODE=disabled|dev|all; sqladmin + itsdangerous.
DEPENDS ON: —""",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="admin_panel/python",
                dependencies=("sqladmin>=0.20.0", "itsdangerous>=2.2.0"),
                env_vars=(("ADMIN_PANEL_MODE", "dev"),),
            ),
        },
    )
)


register(
    FeatureSpec(
        key="webhooks",
        display_label="Outbound Webhooks",
        cli_flag="--include-webhooks",
        stability="beta",
        default_enabled=False,
        category=FeatureCategory.PLATFORM,
        description="""\
A registry + HMAC-SHA256 signed outbound delivery pipeline. Clients POST
to /api/v1/webhooks to register a target URL; your code calls `fireEvent`
to deliver a signed JSON payload to every matching endpoint. Receiver
verifies the same way across all three backends — the signature header
format is identical.

WHEN TO ENABLE: customer-facing platforms that publish events (billing,
content changes, workflow completions). v1 is synchronous best-effort;
pair with `background_tasks` when you need retry semantics.
BACKENDS: python, node, rust
ENDPOINTS: /api/v1/webhooks (CRUD + /{id}/test fire)
REQUIRES: httpx (py); hmac + sha2 crates (rust); migration 0005 (py only)
DEPENDS ON: —""",
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


register(
    FeatureSpec(
        key="cli_commands",
        display_label="Service CLI Extensions",
        cli_flag="--include-cli-commands",
        stability="beta",
        default_enabled=False,
        category=FeatureCategory.PLATFORM,
        description="""\
Extends the generated service's `app` typer CLI with operational
subcommands: `app info show` (environment dump), `app tools list`/`invoke`
(exercise registered agent tools from the shell), `app rag ingest`
(ingest a local file into the knowledge base). Each subcommand degrades
gracefully — if its prerequisite feature isn't enabled, it prints a hint
and exits non-zero rather than import-crashing.

WHEN TO ENABLE: teams that SSH into containers for ops tasks or run
scheduled Kubernetes Jobs off the same image.
BACKENDS: python
ENDPOINTS: none — CLI surface only.
REQUIRES: typer (already in base template).
DEPENDS ON: — (subcommands silently skip if prerequisites are off)""",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="cli_commands/python",
            ),
        },
    )
)


register(
    FeatureSpec(
        key="conversation_persistence",
        display_label="Chat History",
        cli_flag="--include-conversation-persistence",
        stability="beta",
        default_enabled=False,
        category=FeatureCategory.CONVERSATIONAL_AI,
        description="""\
SQLAlchemy models + Pydantic schemas + a repository for `Conversation`,
`Message`, and `ToolCall` rows, plus the Alembic migration that creates
them. Rows are tenant + user scoped. This is the foundation the agent
stream persists history to.

WHEN TO ENABLE: anything storing chat turns — support bots, internal
copilots, any product with a multi-turn conversational surface.
BACKENDS: python
ENDPOINTS: none — DB layer; use via ConversationRepository.
REQUIRES: migration 0002 applied (`alembic upgrade head`).
DEPENDS ON: —""",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="conversation_persistence/python",
            ),
        },
    )
)


register(
    FeatureSpec(
        key="agent_streaming",
        display_label="Agent Stream",
        cli_flag="--include-agent-streaming",
        stability="experimental",
        default_enabled=False,
        depends_on=("conversation_persistence",),
        category=FeatureCategory.CONVERSATIONAL_AI,
        description="""\
A WebSocket endpoint at /api/v1/ws/agent that streams typed AgentEvent
JSON frames (conversation_created, user_prompt, text_delta, tool_call,
tool_result, agent_status, error). Ships with an echo runner out of the
box and a runner-dispatch module that prefers `app.agents.llm_runner` if
present — so enabling the `agent` feature swaps in a real LLM loop with
zero endpoint churn.

WHEN TO ENABLE: any chat UI that renders streaming text or tool calls.
BACKENDS: python
ENDPOINTS: /api/v1/ws/agent (WebSocket)
REQUIRES: nothing at runtime (echo mode).
DEPENDS ON: conversation_persistence""",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="agent_streaming/python",
            ),
        },
    )
)


register(
    FeatureSpec(
        key="response_cache",
        display_label="Response Cache",
        cli_flag="--include-response-cache",
        stability="beta",
        default_enabled=False,
        capabilities=("redis",),
        category=FeatureCategory.RELIABILITY,
        description="""\
Wires a cache backend at startup so route handlers can decorate themselves
for server-side response caching. Python uses fastapi-cache2 with a Redis
backend (falls back to in-memory if RESPONSE_CACHE_URL isn't set); Node
uses @fastify/caching. No blanket behavior change — handlers opt in
per-endpoint.

WHEN TO ENABLE: read-heavy routes where the same payload is served
repeatedly (product catalogues, settings, public dashboards).
BACKENDS: python, node
ENDPOINTS: none — decorate existing routes with @cache(expire=N).
REQUIRES: RESPONSE_CACHE_URL pointing at Redis (recommended for prod).
DEPENDS ON: —""",
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


register(
    FeatureSpec(
        key="background_tasks",
        display_label="Task Queue",
        cli_flag="--include-background-tasks",
        stability="beta",
        default_enabled=False,
        capabilities=("redis",),
        category=FeatureCategory.ASYNC_WORK,
        description="""\
A Redis-backed job queue + example task + worker binary. Define jobs as
regular async functions, enqueue them from request handlers, process them
out-of-process in a dedicated worker container. Ships with Taskiq (Python),
BullMQ + ioredis (Node), and Apalis (Rust) — three different ecosystems
with the same env-var convention (`TASKIQ_BROKER_URL`).

WHEN TO ENABLE: any service doing work users shouldn't wait for — emails,
webhooks retries, RAG ingestion, image processing, LLM fan-outs.
BACKENDS: python, node, rust
ENDPOINTS: none; run the worker alongside the main app.
REQUIRES: TASKIQ_BROKER_URL → Redis.
DEPENDS ON: —""",
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


register(
    FeatureSpec(
        key="rag_pipeline",
        display_label="Knowledge Search",
        cli_flag="--include-rag",
        stability="experimental",
        default_enabled=False,
        depends_on=("conversation_persistence",),
        capabilities=("postgres-pgvector",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
A complete RAG stack: OpenAI embeddings + pgvector storage with an HNSW
index (cosine) + recursive chunker + PDF ingestion + retriever that
enforces tenant isolation. Ships a `rag_search` agent tool that
auto-registers into the ToolRegistry when `agent_tools` is also enabled,
so the LLM can call RAG with no extra wiring. Alternative vector stores
(Qdrant, Chroma, Milvus, Weaviate, Pinecone, plain PostgreSQL) plug in
over this same pipeline — see the Knowledge — <backend> features.

WHEN TO ENABLE: any agent that needs to consult a corpus of documents.
BACKENDS: python
ENDPOINTS: /api/v1/rag/{ingest, ingest-pdf, search}
REQUIRES: migration 0004 (creates `vector` extension + HNSW index);
OPENAI_API_KEY.
DEPENDS ON: conversation_persistence""",
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


register(
    FeatureSpec(
        key="rag_sync_tasks",
        display_label="Knowledge Ingest Queue",
        cli_flag="--include-rag-sync-tasks",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline", "background_tasks"),
        category=FeatureCategory.ASYNC_WORK,
        description="""\
Taskiq tasks that move RAG ingestion off the request thread. Enqueue with
`await ingest_text_task.kiq(...)` or `ingest_pdf_bytes_task.kiq(...)` from
any handler — the worker picks it up and runs chunk + embed + store in
the background. The endpoint returns immediately with a task ID.

WHEN TO ENABLE: ingesting large corpora or accepting user uploads where
users shouldn't wait on the embedding round-trip.
BACKENDS: python
ENDPOINTS: none — task handles available as `app.worker.rag_tasks`.
REQUIRES: running Taskiq worker + OPENAI_API_KEY.
DEPENDS ON: rag_pipeline, background_tasks""",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_sync_tasks/python",
            ),
        },
    )
)


register(
    FeatureSpec(
        key="rag_embeddings_voyage",
        display_label="Knowledge — Voyage Embeddings",
        cli_flag="--include-rag-voyage",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
Voyage AI as an alternative embeddings provider. Ships a drop-in Python
module; users change one import to swap from OpenAI. Voyage typically
outperforms OpenAI's text-embedding-3-small on retrieval benchmarks and
offers domain-specialized models (voyage-code-3, voyage-finance-2).
**Not wire-compatible with OpenAI embeddings — rebuild any existing
vector collection after switching.**

WHEN TO ENABLE: you want higher retrieval quality or a domain-specialized
embedding model.
BACKENDS: python
ENDPOINTS: none — swap `from app.rag.embeddings import embed` to
`from app.rag.voyage_embeddings import embed`.
REQUIRES: VOYAGE_API_KEY.
DEPENDS ON: rag_pipeline""",
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


register(
    FeatureSpec(
        key="rag_reranking",
        display_label="Knowledge Reranker",
        cli_flag="--include-rag-reranking",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
Post-retrieval rerank pass. Oversamples candidates from the vector store
and reorders them with a cross-encoder so top-K is sharper than pure
embedding similarity gives you. Cohere is the default provider; a local
sentence-transformers cross-encoder is available as an opt-in fallback.
Degrades to a silent no-op when no provider is configured.

WHEN TO ENABLE: retrieval quality matters more than a few hundred ms of
added latency — legal search, technical-doc QA, large corpora.
BACKENDS: python
ENDPOINTS: /api/v1/rag/rerank/search
REQUIRES: COHERE_API_KEY (or a local cross-encoder model on disk).
DEPENDS ON: rag_pipeline""",
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


register(
    FeatureSpec(
        key="rag_milvus",
        display_label="Knowledge — Milvus",
        cli_flag="--include-rag-milvus",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("milvus",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
Milvus backend via AsyncMilvusClient. HNSW index + COSINE distance by
default. Same knobs point at self-hosted Milvus or Zilliz Cloud —
MILVUS_URI is the only thing that changes. Adds parallel
/api/v1/rag/milvus/* endpoints alongside the default pgvector ones, so
multiple backends can coexist during a migration.

WHEN TO ENABLE: you already run Milvus, need billion-scale vector search,
or want Zilliz Cloud's managed variant.
BACKENDS: python
ENDPOINTS: /api/v1/rag/milvus/{ingest, search}
REQUIRES: MILVUS_URI (+ MILVUS_TOKEN for Zilliz Cloud).
DEPENDS ON: rag_pipeline""",
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


register(
    FeatureSpec(
        key="rag_weaviate",
        display_label="Knowledge — Weaviate",
        cli_flag="--include-rag-weaviate",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("weaviate",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
Weaviate v4 async backend. Uses Weaviate's HNSW + cosine, with
server-side vectorizer disabled so we stay in control of which
embeddings model produced the vectors. Parallel /api/v1/rag/weaviate/*
endpoints; multitenancy is enforced in the filter, not at collection
level.

WHEN TO ENABLE: you already run Weaviate or want hybrid BM25 + vector
search (Weaviate supports it natively).
BACKENDS: python
ENDPOINTS: /api/v1/rag/weaviate/{ingest, search}
REQUIRES: WEAVIATE_URL (+ WEAVIATE_API_KEY if the cluster is secured).
DEPENDS ON: rag_pipeline""",
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


register(
    FeatureSpec(
        key="rag_pinecone",
        display_label="Knowledge — Pinecone",
        cli_flag="--include-rag-pinecone",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("pinecone",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
Managed Pinecone backend. Uses namespace-per-tenant for hard isolation
across customers. Note: the Pinecone index has to be pre-created in the
Pinecone console or via their control plane — the feature does not
auto-create it, on purpose, since index creation is a billable operation.
Parallel /api/v1/rag/pinecone/* endpoints.

WHEN TO ENABLE: you want a fully managed vector DB with zero ops, and
SaaS-tier billing is acceptable.
BACKENDS: python
ENDPOINTS: /api/v1/rag/pinecone/{ingest, search}
REQUIRES: PINECONE_API_KEY, a pre-created PINECONE_INDEX (dimension must
match EMBEDDING_DIM).
DEPENDS ON: rag_pipeline""",
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


register(
    FeatureSpec(
        key="rag_chroma",
        display_label="Knowledge — Chroma",
        cli_flag="--include-rag-chroma",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("chroma",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
Chroma vector-store backend. Uses the AsyncHttpClient so the same code
talks to a docker-compose Chroma server container or to Chroma Cloud —
only CHROMA_URL changes. Parallel /api/v1/rag/chroma/* endpoints sharing
chunker + embeddings + pdf_parser modules with the default pgvector
pipeline.

WHEN TO ENABLE: local-first development workflows; small-to-mid corpora
where a single-container vector store is simpler than running Postgres +
pgvector.
BACKENDS: python
ENDPOINTS: /api/v1/rag/chroma/{ingest, search}
REQUIRES: CHROMA_URL reachable (local container or Chroma Cloud).
DEPENDS ON: rag_pipeline""",
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


register(
    FeatureSpec(
        key="rag_postgresql",
        display_label="Knowledge — PostgreSQL",
        cli_flag="--include-rag-postgresql",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
A plain-PostgreSQL backend for managed DB environments where the
pgvector extension can't be installed (e.g. restricted hosted Postgres).
Stores embeddings as JSONB and computes cosine similarity in Python
post-fetch. Slower than pgvector at scale, but zero new infrastructure.
Migration 0006 creates the `rag_chunks` table.

WHEN TO ENABLE: you're on a hosted Postgres (Supabase free tier, Heroku
Postgres, some RDS setups) and pgvector is not an option.
BACKENDS: python
ENDPOINTS: /api/v1/rag/pg/{ingest, search}
REQUIRES: migration 0006 applied (`alembic upgrade head`).
DEPENDS ON: rag_pipeline""",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="rag_postgresql/python",
            ),
        },
    )
)


register(
    FeatureSpec(
        key="rag_qdrant",
        display_label="Knowledge — Qdrant",
        cli_flag="--include-rag-qdrant",
        stability="experimental",
        default_enabled=False,
        depends_on=("rag_pipeline",),
        capabilities=("qdrant",),
        category=FeatureCategory.KNOWLEDGE,
        description="""\
Qdrant vector-store backend with tenant-scoped payload filtering and
cosine similarity. Parallel /api/v1/rag/qdrant/* endpoints coexist with
the pgvector ones, so you can migrate incrementally — copy chunks over,
A/B the retriever quality, then delete the old path.

WHEN TO ENABLE: you want Rust-level query speed, disk-offloaded
collections for large corpora, or you already run Qdrant in your stack.
BACKENDS: python
ENDPOINTS: /api/v1/rag/qdrant/{ingest, search}
REQUIRES: QDRANT_URL (+ QDRANT_API_KEY for Qdrant Cloud).
DEPENDS ON: rag_pipeline""",
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


register(
    FeatureSpec(
        key="file_upload",
        display_label="Chat Attachments",
        cli_flag="--include-file-upload",
        stability="beta",
        default_enabled=False,
        depends_on=("conversation_persistence",),
        category=FeatureCategory.CONVERSATIONAL_AI,
        description="""\
Multipart upload + download endpoints under /api/v1/chat-files with
local-disk storage, configurable size + MIME allow-list, and a ChatFile
SQLAlchemy model + migration for users who want DB persistence. The
endpoint is storage-only by default (no DB write) so dropping it in
doesn't require Dishka DI changes; wire the ChatFile model into your
repo layer as needed.

WHEN TO ENABLE: chat UIs that accept user-supplied files — images,
PDFs, CSVs — for the LLM to reason over.
BACKENDS: python
ENDPOINTS: /api/v1/chat-files (upload + download by id)
REQUIRES: UPLOAD_DIR writable; MAX_UPLOAD_SIZE; ALLOWED_MIME_TYPES
(empty = allow all).
DEPENDS ON: conversation_persistence""",
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


register(
    FeatureSpec(
        key="agent",
        display_label="LLM Agent",
        cli_flag="--include-agent",
        stability="experimental",
        default_enabled=False,
        depends_on=("agent_streaming", "agent_tools"),
        category=FeatureCategory.CONVERSATIONAL_AI,
        description="""\
A pydantic-ai LLM loop that swaps in for the echo runner shipped by
agent_streaming — no endpoint or WebSocket-contract change needed. Auto-
picks the provider from LLM_PROVIDER (anthropic / openai / google /
openrouter). Every tool registered in the ToolRegistry is bridged into
pydantic-ai automatically, so adding a tool is one register() call. A
missing API key produces a clean error event on the stream rather than
crashing the process.

WHEN TO ENABLE: you want a real LLM behind the agent WebSocket.
BACKENDS: python
ENDPOINTS: none — hot-swaps the runner that serves /api/v1/ws/agent.
REQUIRES: one of ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY /
OPENROUTER_API_KEY, matching LLM_PROVIDER.
DEPENDS ON: agent_streaming, agent_tools""",
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


register(
    FeatureSpec(
        key="agent_tools",
        display_label="Tool Registry",
        cli_flag="--include-agent-tools",
        stability="experimental",
        default_enabled=False,
        category=FeatureCategory.CONVERSATIONAL_AI,
        description="""\
A lightweight Tool base class, a process-wide registry, and two
pre-baked tools (`current_datetime`, `web_search` via Tavily). When
`rag_pipeline` is enabled it auto-registers `rag_search` too. Exposes a
/api/v1/tools list + invoke endpoint so humans (or test harnesses) can
exercise tools without an LLM loop attached.

WHEN TO ENABLE: anything that needs tool-calling — pair with `agent`
for pydantic-ai bridging, or use standalone for shell-driven tooling.
BACKENDS: python
ENDPOINTS: /api/v1/tools (GET list, POST invoke)
REQUIRES: TAVILY_API_KEY for the web_search tool (optional).
DEPENDS ON: —""",
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
        display_label="Deep Health Checks",
        cli_flag="--include-enhanced-health",
        stability="beta",
        default_enabled=False,
        category=FeatureCategory.OBSERVABILITY,
        description="""\
Upgrades the default /health check to a deep readiness probe that
verifies DB connectivity, Redis ping, and Keycloak health endpoint
reachability. Each dependency reports individually so an orchestrator
(Kubernetes readiness gate, load balancer) sees which specific
downstream is down rather than an opaque 503.

WHEN TO ENABLE: Kubernetes / ECS deployments where rolling updates should
gate on actual dependency health, not just process-alive.
BACKENDS: python, node, rust
ENDPOINTS: /health (replaces the shallow default)
REQUIRES: REDIS_URL, KEYCLOAK_HEALTH_URL pointing at whichever services
matter for "ready" in your stack.
DEPENDS ON: —""",
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
        display_label="Distributed Tracing",
        cli_flag="--include-observability",
        stability="stable",
        default_enabled=False,
        category=FeatureCategory.OBSERVABILITY,
        description="""\
Distributed tracing + structured logs wired out of the box. Python uses
Logfire (which exports OTLP under the hood); Node uses @opentelemetry
auto-instrumentations for HTTP / DB / Fastify spans; Rust uses
tracing-opentelemetry + OTLP gRPC. All three honour the same OTel
semantic-convention service name so your tracing backend (Jaeger, Tempo,
Honeycomb, Datadog APM, Logfire) sees one service-map across languages.

WHEN TO ENABLE: any multi-service deployment where you need to trace a
request hop across languages / processes.
BACKENDS: python, node, rust
ENDPOINTS: none — spans emitted ambient; traces visible in the OTLP
collector.
REQUIRES: OTEL_EXPORTER_OTLP_ENDPOINT (or LOGFIRE_TOKEN on Python).
DEPENDS ON: —""",
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


_AGENTS_MD_IMPL = FragmentImplSpec(fragment_dir="agents_md/all", scope="project")
register(
    FeatureSpec(
        key="agents_md",
        display_label="AI Agent Handbook",
        cli_flag="--include-agents-md",
        stability="stable",
        default_enabled=True,
        category=FeatureCategory.PLATFORM,
        description="""\
Drops AGENTS.md + CLAUDE.md at the project root so AI coding agents
(Claude Code, Cursor, Copilot workspaces) have a structured orientation
document before they touch generated code. Covers the feature stamp,
backend layout, test commands, and the house conventions so agents ship
PRs that match the project's style on the first try.

WHEN TO ENABLE: any project a team intends to let AI agents contribute
to. Leave on by default — it's a pair of harmless markdown files.
BACKENDS: python, node, rust (same content, project-scoped)
ENDPOINTS: none — on-disk docs.
REQUIRES: nothing
DEPENDS ON: —""",
        implementations={
            BackendLanguage.PYTHON: _AGENTS_MD_IMPL,
            BackendLanguage.NODE: _AGENTS_MD_IMPL,
            BackendLanguage.RUST: _AGENTS_MD_IMPL,
        },
    )
)
