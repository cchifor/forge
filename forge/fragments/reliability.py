"""Reliability fragments — DB connection pools + circuit breakers.

These wrap the per-backend persistence + outbound-HTTP layers with
production-shape defaults: pool sizing for SQLAlchemy/Prisma/sqlx,
circuit breaker thresholds for Purgatory/Opossum.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

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
