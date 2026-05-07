"""Fragments for built-in middleware features.

POC scope: ``correlation_id`` only.

Fragment template trees ship from this package using absolute paths via
``Path(__file__).resolve().parent / "templates"`` — the same convention
plugin authors use (see ``docs/plugin-development.md``). The injector's
``_resolve_fragment_dir`` returns absolute paths verbatim, so built-in
features and plugin features flow through identical resolution code.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec
from forge.middleware_spec import MiddlewareSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"

register_fragment(
    Fragment(
        name="correlation_id",
        order=90,  # outermost middleware — registers last, runs first
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=str(_TEMPLATES / "correlation_id" / "python"),
            ),
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
