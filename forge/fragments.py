"""Fragment registry — the implementation side of forge's config layer.

A **Fragment** describes how to apply a named template fragment (living
under ``forge/templates/_fragments/<name>/<backend>/``) to a generated
project. Fragments are internal plumbing: users never name them
directly. Users select **Options** (``forge/options.py``); each Option
enumerates the Fragments that realise each chosen value via its
``enables`` map.

Fragment layout on disk is:

    <fragment_name>/<backend_lang>/
        inject.yaml  — list of (target, marker, snippet) injections
        files/       — verbatim files to copy into the generated project
        deps.yaml    — dependencies added to pyproject/package.json/Cargo.toml
        env.yaml     — env vars appended to .env.example

All four are optional; a fragment can be pure-injection, pure-files, or
any mix. ``scope="project"`` applies once to the project root instead of
each backend's directory (use for cross-cutting files like AGENTS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from forge.config import BackendLanguage

# Marker format used to locate injection points in base templates.
# Python/Rust/TS source files use `# FORGE:NAME` / `// FORGE:NAME`.
# YAML uses `# FORGE:NAME`. Markers must be unique per file.
MARKER_PREFIX = "FORGE:"

# Root directory under forge/templates where all fragments live.
FRAGMENTS_DIRNAME = "_fragments"


FragmentScope = Literal["backend", "project"]


@dataclass(frozen=True)
class FragmentImplSpec:
    """Per-backend (or project-scope) implementation of a fragment.

    The fragment directory layout is documented in the module docstring.
    ``scope="backend"`` (default) applies to each supporting backend's
    directory. ``scope="project"`` applies once to the project root after
    all backends are generated — use for cross-cutting files.
    """

    fragment_dir: str  # relative to forge/templates/_fragments
    scope: FragmentScope = "backend"
    dependencies: tuple[str, ...] = ()
    env_vars: tuple[tuple[str, str], ...] = ()
    settings_keys: tuple[str, ...] = ()
    post_hooks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fragment:
    """A named template fragment with per-backend implementations.

    Fragments own only implementation details: which backends they
    target, what they depend on, and what infra capabilities they
    require. User-visible metadata (summary, description, stability,
    category) lives on the Options that reference them.
    """

    name: str
    implementations: dict[BackendLanguage, FragmentImplSpec]
    # Other fragment names that must be in the plan if this one is.
    depends_on: tuple[str, ...] = ()
    # Mutual-exclusion — fragments that cannot coexist with this one.
    conflicts_with: tuple[str, ...] = ()
    # Runtime capabilities this fragment needs (redis, postgres-pgvector,
    # qdrant, etc.). docker_manager reads these to provision extras.
    capabilities: tuple[str, ...] = ()
    # Numeric ordering within a topological layer — lower = earlier apply.
    # Controls middleware registration ordering on before-marker
    # injections.
    order: int = 100

    def supports(self, language: BackendLanguage) -> bool:
        return language in self.implementations


FRAGMENT_REGISTRY: dict[str, Fragment] = {}


def register_fragment(frag: Fragment) -> None:
    """Register a fragment. Raises on duplicate name."""
    if frag.name in FRAGMENT_REGISTRY:
        raise ValueError(f"Fragment {frag.name!r} is already registered")
    FRAGMENT_REGISTRY[frag.name] = frag


def fragments_root() -> Path:
    """Filesystem path to the _fragments root under forge/templates/."""
    return Path(__file__).parent / "templates" / FRAGMENTS_DIRNAME


# -----------------------------------------------------------------------------
# Registered fragments
# -----------------------------------------------------------------------------

register_fragment(
    Fragment(
        name="correlation_id",
        order=90,  # outermost middleware — registers last, runs first
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="correlation_id/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="rate_limit",
        order=50,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="rate_limit/python"),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="rate_limit/node",
                dependencies=("@fastify/rate-limit@10.3.0",),
            ),
            BackendLanguage.RUST: FragmentImplSpec(fragment_dir="rate_limit/rust"),
        },
    )
)


register_fragment(
    Fragment(
        name="security_headers",
        order=80,  # below correlation_id (90) so registers inside it
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="security_headers/python"),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="security_headers/node",
                dependencies=("@fastify/helmet@13.0.1",),
            ),
            BackendLanguage.RUST: FragmentImplSpec(fragment_dir="security_headers/rust"),
        },
    )
)


register_fragment(
    Fragment(
        name="pii_redaction",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="pii_redaction/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="response_cache",
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


register_fragment(
    Fragment(
        name="observability",
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


register_fragment(
    Fragment(
        name="enhanced_health",
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


register_fragment(
    Fragment(
        name="background_tasks",
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
                dependencies=("apalis@0.6", "apalis-redis@0.6"),
                env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_sync_tasks",
        depends_on=("rag_pipeline", "background_tasks"),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="rag_sync_tasks/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="conversation_persistence",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="conversation_persistence/python"
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="agent_streaming",
        depends_on=("conversation_persistence",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="agent_streaming/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="agent_tools",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="agent_tools/python",
                dependencies=("httpx>=0.28.0",),
                env_vars=(("TAVILY_API_KEY", ""),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="agent",
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


register_fragment(
    Fragment(
        name="file_upload",
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


register_fragment(
    Fragment(
        name="rag_pipeline",
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


register_fragment(
    Fragment(
        name="rag_embeddings_voyage",
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


register_fragment(
    Fragment(
        name="rag_reranking",
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


register_fragment(
    Fragment(
        name="rag_milvus",
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


register_fragment(
    Fragment(
        name="rag_weaviate",
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


register_fragment(
    Fragment(
        name="rag_pinecone",
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


register_fragment(
    Fragment(
        name="rag_chroma",
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


register_fragment(
    Fragment(
        name="rag_postgresql",
        depends_on=("rag_pipeline",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="rag_postgresql/python"),
        },
    )
)


register_fragment(
    Fragment(
        name="rag_qdrant",
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


register_fragment(
    Fragment(
        name="admin_panel",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="admin_panel/python",
                dependencies=("sqladmin>=0.20.0", "itsdangerous>=2.2.0"),
                env_vars=(("ADMIN_PANEL_MODE", "dev"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="webhooks",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="webhooks/python",
                dependencies=("httpx>=0.28.0",),
            ),
            BackendLanguage.NODE: FragmentImplSpec(fragment_dir="webhooks/node"),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="webhooks/rust",
                dependencies=("hmac@0.12", "sha2@0.10"),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="cli_commands",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="cli_commands/python"),
        },
    )
)


_AGENTS_MD_IMPL = FragmentImplSpec(fragment_dir="agents_md/all", scope="project")
register_fragment(
    Fragment(
        name="agents_md",
        implementations={
            BackendLanguage.PYTHON: _AGENTS_MD_IMPL,
            BackendLanguage.NODE: _AGENTS_MD_IMPL,
            BackendLanguage.RUST: _AGENTS_MD_IMPL,
        },
    )
)


register_fragment(
    Fragment(
        name="mcp_server",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="mcp_server/python",
                env_vars=(("MCP_CONFIG_PATH", "mcp.config.json"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="mcp_ui",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="mcp_ui",
                scope="project",
            ),
        },
    )
)


# -- Ports-and-adapters (ADR-002, Phase 2.3) ----------------------------------
# Reference implementation of the port+adapter pattern. The full refactor
# of rag_* fragments into this shape lands in 1.0.0a2. For the alpha, we
# ship the port module and the Qdrant adapter so plugin authors have a
# concrete reference to model new adapters on.

register_fragment(
    Fragment(
        name="vector_store_port",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_port/python"
            ),
        },
    )
)

register_fragment(
    Fragment(
        name="security_csp",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="security_csp",
                scope="project",
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="security_csp",
                scope="project",
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="security_csp",
                scope="project",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="security_sbom",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="security_sbom/python",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="observability_otel",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="observability_otel/python",
                dependencies=(
                    "opentelemetry-api>=1.28.0",
                    "opentelemetry-sdk>=1.28.0",
                    "opentelemetry-exporter-otlp-proto-grpc>=1.28.0",
                    "opentelemetry-instrumentation-fastapi>=0.49b0",
                    "opentelemetry-instrumentation-httpx>=0.49b0",
                ),
                env_vars=(
                    ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                    ("OTEL_SERVICE_NAME", ""),
                    ("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=dev"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="observability_otel/node",
                dependencies=(
                    "@opentelemetry/sdk-node@^0.55.0",
                    "@opentelemetry/resources@^1.28.0",
                    "@opentelemetry/exporter-trace-otlp-grpc@^0.55.0",
                    "@opentelemetry/auto-instrumentations-node@^0.51.0",
                ),
                env_vars=(
                    ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                    ("OTEL_SERVICE_NAME", ""),
                ),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="observability_otel/rust",
                dependencies=(
                    "opentelemetry@0.27",
                    "opentelemetry_sdk@0.27",
                    "opentelemetry-otlp@0.27",
                    "tracing-opentelemetry@0.28",
                ),
                env_vars=(
                    ("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                    ("OTEL_SERVICE_NAME", ""),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="reliability_connection_pool",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="reliability_connection_pool/python",
                env_vars=(
                    ("SQLALCHEMY_POOL_SIZE", "20"),
                    ("SQLALCHEMY_MAX_OVERFLOW", "10"),
                    ("SQLALCHEMY_POOL_PRE_PING", "true"),
                    ("SQLALCHEMY_POOL_RECYCLE", "1800"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="reliability_connection_pool/node",
                env_vars=(
                    ("PRISMA_CONNECTION_LIMIT", "20"),
                    ("PRISMA_POOL_TIMEOUT", "10"),
                ),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="reliability_connection_pool/rust",
                env_vars=(
                    ("SQLX_MAX_CONNECTIONS", "20"),
                    ("SQLX_MIN_CONNECTIONS", "2"),
                    ("SQLX_ACQUIRE_TIMEOUT_SECS", "10"),
                    ("SQLX_IDLE_TIMEOUT_SECS", "600"),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="reliability_circuit_breaker",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="reliability_circuit_breaker/python",
                dependencies=("purgatory>=3.0.0",),
                env_vars=(
                    ("CIRCUIT_BREAKER_THRESHOLD", "5"),
                    ("CIRCUIT_BREAKER_RESET_TIMEOUT", "30"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="reliability_circuit_breaker/node",
                dependencies=("opossum@9.0.0",),
                env_vars=(
                    ("CIRCUIT_BREAKER_TIMEOUT_MS", "10000"),
                    ("CIRCUIT_BREAKER_ERROR_THRESHOLD_PCT", "50"),
                    ("CIRCUIT_BREAKER_RESET_TIMEOUT_MS", "30000"),
                ),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="reliability_circuit_breaker/rust",
                env_vars=(
                    ("CIRCUIT_BREAKER_THRESHOLD", "5"),
                    ("CIRCUIT_BREAKER_RESET_TIMEOUT", "30"),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="vector_store_qdrant",
        depends_on=("vector_store_port",),
        capabilities=("qdrant",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_qdrant/python",
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


register_fragment(
    Fragment(
        name="vector_store_chroma",
        depends_on=("vector_store_port",),
        capabilities=("chroma",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_chroma/python",
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


register_fragment(
    Fragment(
        name="vector_store_pinecone",
        depends_on=("vector_store_port",),
        capabilities=("pinecone",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_pinecone/python",
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


register_fragment(
    Fragment(
        name="vector_store_milvus",
        depends_on=("vector_store_port",),
        capabilities=("milvus",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_milvus/python",
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


register_fragment(
    Fragment(
        name="vector_store_weaviate",
        depends_on=("vector_store_port",),
        capabilities=("weaviate",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_weaviate/python",
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


register_fragment(
    Fragment(
        name="vector_store_postgres",
        depends_on=("vector_store_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="vector_store_postgres/python",
            ),
        },
    )
)


# -- LLM provider port + adapters (1.0.0a2) ---------------------------------

register_fragment(
    Fragment(
        name="llm_port",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="llm_port/python",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="llm_openai",
        depends_on=("llm_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="llm_openai/python",
                dependencies=("openai>=1.54.0",),
                env_vars=(
                    ("OPENAI_API_KEY", ""),
                    ("OPENAI_BASE_URL", ""),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="llm_anthropic",
        depends_on=("llm_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="llm_anthropic/python",
                dependencies=("anthropic>=0.40.0",),
                env_vars=(("ANTHROPIC_API_KEY", ""),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="llm_ollama",
        depends_on=("llm_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="llm_ollama/python",
                dependencies=("ollama>=0.4.0",),
                env_vars=(("OLLAMA_HOST", "http://localhost:11434"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="llm_bedrock",
        depends_on=("llm_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="llm_bedrock/python",
                dependencies=("aioboto3>=13.2.0",),
                env_vars=(("AWS_REGION", "us-east-1"),),
            ),
        },
    )
)


# -- Queue port + adapters (1.0.0a2) ----------------------------------------

register_fragment(
    Fragment(
        name="queue_port",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="queue_port/python",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="queue_redis",
        depends_on=("queue_port",),
        capabilities=("redis",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="queue_redis/python",
                dependencies=("redis>=5.2.0",),
                env_vars=(("REDIS_URL", "redis://redis:6379/0"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="queue_sqs",
        depends_on=("queue_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="queue_sqs/python",
                dependencies=("aioboto3>=13.2.0",),
                env_vars=(("AWS_REGION", "us-east-1"),),
            ),
        },
    )
)


# -- Object-store port + adapters (1.0.0a2) ---------------------------------

register_fragment(
    Fragment(
        name="object_store_port",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="object_store_port/python",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="object_store_s3",
        depends_on=("object_store_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="object_store_s3/python",
                dependencies=("aioboto3>=13.2.0",),
                env_vars=(
                    ("AWS_REGION", "us-east-1"),
                    ("S3_ENDPOINT_URL", ""),
                    ("AWS_ACCESS_KEY_ID", ""),
                    ("AWS_SECRET_ACCESS_KEY", ""),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="object_store_local",
        depends_on=("object_store_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="object_store_local/python",
                env_vars=(("OBJECT_STORE_ROOT", "/var/lib/forge/objects"),),
            ),
        },
    )
)
