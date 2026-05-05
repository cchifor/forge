"""HTTP middleware fragments — request-path cross-cutting concerns.

The fragments here register middleware in the per-backend HTTP server's
middleware chain. Order is significant: ``correlation_id`` is outermost
(order=90) so its context is set before any other middleware runs;
``security_headers`` (order=80) is below it; ``rate_limit`` (order=50)
sits in the middle.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec
from forge.middleware_spec import MiddlewareSpec

register_fragment(
    Fragment(
        name="correlation_id",
        order=90,  # outermost middleware — registers last, runs first
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="correlation_id/python"),
        },
        # Epic K (1.1.0-alpha.1) — MiddlewareSpec replaces the
        # correlation_id/python/inject.yaml file. The files/ tree (the
        # actual CorrelationIdMiddleware class) still lives on disk; only
        # the import + app.add_middleware(...) ceremony is declarative now.
        middlewares=(
            MiddlewareSpec(
                name="correlation_id",
                backend=BackendLanguage.PYTHON,
                order=90,
                import_snippet=("from app.middleware.correlation import CorrelationIdMiddleware"),
                register_snippet=(
                    "# Correlation ID (outermost — runs first, sets context for all inner middleware)\n"
                    "app.add_middleware(CorrelationIdMiddleware)"
                ),
            ),
        ),
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
