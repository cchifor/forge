"""``reliability.*`` — pool tuning, circuit breakers."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="reliability.connection_pool",
        type=OptionType.BOOL,
        default=True,
        summary="Sane SQLAlchemy async pool defaults (size=20, overflow=10, pre_ping, recycle=30m).",
        description="""\
Emits ``app/core/db_pool.py`` with production-ready SQLAlchemy pool
settings and env-var overrides. Without this fragment, generated
projects run on SQLAlchemy's default pool_size=5, which saturates under
moderate burst traffic and produces mysterious 99p tail latency.

BACKENDS: python
TUNABLE VIA ENV: SQLALCHEMY_POOL_SIZE, SQLALCHEMY_MAX_OVERFLOW,
SQLALCHEMY_POOL_PRE_PING, SQLALCHEMY_POOL_RECYCLE.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("reliability_connection_pool",)},
    )
)


register_option(
    Option(
        path="reliability.circuit_breaker",
        type=OptionType.BOOL,
        default=False,
        summary="Circuit breaker for outbound HTTP calls (LLM, vector store, auth).",
        description="""\
Emits ``app/core/circuit_breaker.py`` backed by the purgatory library.
Wraps downstream dependencies so a flaky provider doesn't cascade
failures into every request.

BACKENDS: python
DEPENDENCY: purgatory>=3.0.0
TUNABLE VIA ENV: CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_RESET_TIMEOUT.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("reliability_circuit_breaker",)},
    )
)
