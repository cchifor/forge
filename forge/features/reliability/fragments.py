"""Reliability fragments — DB connection pools + circuit breakers.

These wrap the per-backend persistence + outbound-HTTP layers with
production-shape defaults: pool sizing for SQLAlchemy/Prisma/sqlx,
circuit breaker thresholds for Purgatory/Opossum.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="reliability_connection_pool",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("reliability_connection_pool", "python"),
                    env_vars=(
                        ("SQLALCHEMY_POOL_SIZE", "20"),
                        ("SQLALCHEMY_MAX_OVERFLOW", "10"),
                        ("SQLALCHEMY_POOL_PRE_PING", "true"),
                        ("SQLALCHEMY_POOL_RECYCLE", "1800"),
                    ),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("reliability_connection_pool", "node"),
                    env_vars=(
                        ("PRISMA_CONNECTION_LIMIT", "20"),
                        ("PRISMA_POOL_TIMEOUT", "10"),
                    ),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("reliability_connection_pool", "rust"),
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

    api.add_fragment(
        Fragment(
            name="reliability_circuit_breaker",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("reliability_circuit_breaker", "python"),
                    dependencies=("purgatory>=3.0.0",),
                    env_vars=(
                        ("CIRCUIT_BREAKER_THRESHOLD", "5"),
                        ("CIRCUIT_BREAKER_RESET_TIMEOUT", "30"),
                    ),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("reliability_circuit_breaker", "node"),
                    dependencies=("opossum@9.0.0",),
                    env_vars=(
                        ("CIRCUIT_BREAKER_TIMEOUT_MS", "10000"),
                        ("CIRCUIT_BREAKER_ERROR_THRESHOLD_PCT", "50"),
                        ("CIRCUIT_BREAKER_RESET_TIMEOUT_MS", "30000"),
                    ),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("reliability_circuit_breaker", "rust"),
                    env_vars=(
                        ("CIRCUIT_BREAKER_THRESHOLD", "5"),
                        ("CIRCUIT_BREAKER_RESET_TIMEOUT", "30"),
                    ),
                ),
            },
        )
    )

    # -------------------------------------------------------------------------
    # Pillar E.2 — cache_port + adapters (RFC: deep-gliding-mccarthy §Pillar E).
    #
    # Generic K/V cache port; explicitly distinct from the HTTP-response
    # middleware ``response_cache`` (which keys on request shape via
    # fastapi-cache2). Use cases: idempotency-key dedupe, LLM-response
    # memoization, denormalized read caches.
    #
    # Tier-1 from the start: port + memory + redis adapters on all three
    # backend languages. Auto-derivation tags ``cache_port`` as tier 1
    # because every built-in supports it.
    # -------------------------------------------------------------------------

    api.add_fragment(
        Fragment(
            name="cache_port",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("cache_port", "python"),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("cache_port", "node"),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("cache_port", "rust"),
                    # The trait declaration itself uses async_trait + serde_json
                    # + thiserror; landing the port without these deps would
                    # fail ``cargo check`` even before an adapter wires in.
                    dependencies=(
                        'async-trait = "0.1"',
                        'serde_json = "1"',
                        'thiserror = "1"',
                    ),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="cache_memory",
            depends_on=("cache_port",),
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("cache_memory", "python"),
                    env_vars=(("CACHE_MEMORY_MAX_ENTRIES", "1024"),),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("cache_memory", "node"),
                    env_vars=(("CACHE_MEMORY_MAX_ENTRIES", "1024"),),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("cache_memory", "rust"),
                    dependencies=(
                        'lru = "0.12"',
                        'tokio = { version = "1", features = ["sync"] }',
                    ),
                    env_vars=(("CACHE_MEMORY_MAX_ENTRIES", "1024"),),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="cache_redis",
            depends_on=("cache_port",),
            capabilities=("redis",),
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("cache_redis", "python"),
                    dependencies=("redis>=5.2.0",),
                    env_vars=(("CACHE_REDIS_URL", "redis://redis:6379/3"),),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("cache_redis", "node"),
                    dependencies=("ioredis@5.4.1",),
                    env_vars=(("CACHE_REDIS_URL", "redis://redis:6379/3"),),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("cache_redis", "rust"),
                    dependencies=(
                        'redis = { version = "0.27", features = ["tokio-comp"] }',
                        'tokio = { version = "1", features = ["sync"] }',
                    ),
                    env_vars=(("CACHE_REDIS_URL", "redis://redis:6379/3"),),
                ),
            },
        )
    )
