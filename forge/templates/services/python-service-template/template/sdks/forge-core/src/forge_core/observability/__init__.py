"""forge-core observability — generic cross-cutting telemetry primitives.

Currently a single, stdlib-only building block: the per-request correlation-id
``ContextVar`` set (:mod:`forge_core.observability.correlation`), importable as
``from forge_core.observability import correlation`` or directly as
``from forge_core.observability.correlation import set_correlation_id``.
"""

from forge_core.observability import correlation

__all__ = ["correlation"]
