"""Cross-language middleware registration abstraction (Epic K, 1.1.0-alpha.1).

Every middleware fragment forge ships has the same shape per backend: add
an import line at the language's middleware-imports anchor, and add a
registration block at the middleware-registration anchor. The per-backend
idioms differ (``app.add_middleware(X)`` for FastAPI, ``await
app.register(X, ...)`` for Fastify, ``.layer(X)`` for Axum) but the structure
is identical.

Before Epic K, each fragment shipped one ``inject.yaml`` per backend that
re-encoded the same ceremony with small language-specific tweaks. Adding a
new middleware meant writing three near-identical YAML files; adding a new
backend meant writing six near-identical YAML files for every existing
middleware. Epic K replaces that with one Python dataclass + one snippet per
backend, and a per-backend renderer that emits the right ``_Injection``
records at plan time.

Usage shape inside ``forge/fragments.py``::

    register_fragment(
        Fragment(
            name="correlation_id",
            order=90,
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir="correlation_id/python",
                ),
            },
            middlewares=(
                MiddlewareSpec(
                    name="correlation_id",
                    backend=BackendLanguage.PYTHON,
                    order=90,
                    import_snippet=(
                        "from app.middleware.correlation import CorrelationIdMiddleware"
                    ),
                    register_snippet=(
                        "# Correlation ID (outermost — runs first)\\n"
                        "app.add_middleware(CorrelationIdMiddleware)"
                    ),
                ),
            ),
        )
    )

Epic J (Node+Rust ops parity) is the primary consumer — adding a Python
middleware to Node + Rust becomes "three ``MiddlewareSpec`` literals" instead
of "three copy-pasted ``inject.yaml`` files".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from forge.config import BackendLanguage

if TYPE_CHECKING:
    from forge.feature_injector import _Injection


@dataclass(frozen=True)
class MiddlewareSpec:
    """One middleware registration, targeting one backend.

    Attributes:
        name: Fragment-scoped identifier, used in ``FORGE:BEGIN`` /
            ``FORGE:END`` sentinels. Typically matches ``Fragment.name``.
        backend: Which backend this spec applies to. A fragment supporting
            Python + Node + Rust ships three specs, one per backend.
        order: Insertion order. Lower renders earlier. Middleware fragments
            canonically order by "outermost first": ``correlation_id=90``,
            ``security_headers=80``, ``rate_limit=50``. The `injections`
            produced for a fragment are stable across runs because renderers
            sort by ``(order, name)``.
        import_snippet: The import line injected at the language's
            ``FORGE:MIDDLEWARE_IMPORTS`` anchor.
        register_snippet: The registration block injected at the language's
            ``FORGE:MIDDLEWARE_REGISTRATION`` anchor. May span multiple
            lines — include a leading comment as part of the snippet if you
            want one emitted above the call.
        rust_mod_snippet: Rust-specific. Added at ``FORGE:MOD_REGISTRATION``
            in ``src/middleware/mod.rs`` to expose the submodule. Leave
            ``None`` on non-Rust specs or when the middleware lives in a
            sibling module that's already declared.
    """

    name: str
    backend: BackendLanguage
    order: int
    import_snippet: str
    register_snippet: str
    rust_mod_snippet: str | None = None


# ---------------------------------------------------------------------------
# Per-backend renderers — each produces a tuple of `_Injection` records.
# ---------------------------------------------------------------------------


def _fastapi_target() -> str:
    return "src/app/main.py"


def _fastify_target() -> str:
    return "src/app.ts"


def _axum_target() -> str:
    return "src/app.rs"


def _axum_mod_target() -> str:
    return "src/middleware/mod.rs"


def render_fastapi_middleware(spec: MiddlewareSpec, feature_key: str) -> tuple[_Injection, ...]:
    """Emit _Injection records for a Python/FastAPI middleware.

    Both injections land at ``src/app/main.py`` with ``position=before`` —
    that's the canonical layout every ``middleware_*`` fragment already uses.
    """
    from forge.feature_injector import _Injection  # noqa: PLC0415 — late import

    return (
        _Injection(
            feature_key=feature_key,
            target=_fastapi_target(),
            marker="FORGE:MIDDLEWARE_IMPORTS",
            snippet=spec.import_snippet,
            position="before",
        ),
        _Injection(
            feature_key=feature_key,
            target=_fastapi_target(),
            marker="FORGE:MIDDLEWARE_REGISTRATION",
            snippet=spec.register_snippet,
            position="before",
        ),
    )


def render_fastify_plugin(spec: MiddlewareSpec, feature_key: str) -> tuple[_Injection, ...]:
    """Emit _Injection records for a Node/Fastify plugin registration."""
    from forge.feature_injector import _Injection  # noqa: PLC0415

    return (
        _Injection(
            feature_key=feature_key,
            target=_fastify_target(),
            marker="FORGE:MIDDLEWARE_IMPORTS",
            snippet=spec.import_snippet,
            position="before",
        ),
        _Injection(
            feature_key=feature_key,
            target=_fastify_target(),
            marker="FORGE:MIDDLEWARE_REGISTRATION",
            snippet=spec.register_snippet,
            position="before",
        ),
    )


def render_axum_layer(spec: MiddlewareSpec, feature_key: str) -> tuple[_Injection, ...]:
    """Emit _Injection records for a Rust/Axum tower layer.

    Adds the mod declaration at ``src/middleware/mod.rs`` (position=after)
    before the ``src/app.rs`` import + layer registration.
    """
    from forge.feature_injector import _Injection  # noqa: PLC0415

    out: list[_Injection] = []
    if spec.rust_mod_snippet is not None:
        out.append(
            _Injection(
                feature_key=feature_key,
                target=_axum_mod_target(),
                marker="FORGE:MOD_REGISTRATION",
                snippet=spec.rust_mod_snippet,
                position="after",
            )
        )
    out.append(
        _Injection(
            feature_key=feature_key,
            target=_axum_target(),
            marker="FORGE:MIDDLEWARE_IMPORTS",
            snippet=spec.import_snippet,
            position="before",
        )
    )
    out.append(
        _Injection(
            feature_key=feature_key,
            target=_axum_target(),
            marker="FORGE:MIDDLEWARE_REGISTRATION",
            snippet=spec.register_snippet,
            position="before",
        )
    )
    return tuple(out)


# Dispatch table. Adding a new backend (Go, Java, Elixir) = register a
# renderer here. The INJECTOR_REGISTRY pattern Epic B introduces for AST
# injectors would subsume this in a future unification, but for Epic K the
# dispatch is small enough to keep explicit.
_RENDERERS: dict[
    BackendLanguage,
    Callable[[MiddlewareSpec, str], tuple[_Injection, ...]],
] = {
    BackendLanguage.PYTHON: render_fastapi_middleware,
    BackendLanguage.NODE: render_fastify_plugin,
    BackendLanguage.RUST: render_axum_layer,
}


def render_middleware_injections(
    middlewares: tuple[MiddlewareSpec, ...],
    backend: BackendLanguage,
    feature_key: str,
) -> tuple[_Injection, ...]:
    """Synth injections for every middleware targeting ``backend``.

    Returns injections in deterministic order: ``(spec.order, spec.name)``.
    Specs whose ``backend`` doesn't match the target are silently skipped —
    the applier runs once per backend and only the matching specs fire.
    Unknown backends (e.g. a plugin language with no renderer registered)
    return ``()`` so the injection phase doesn't raise.
    """
    renderer = _RENDERERS.get(backend)
    if renderer is None:
        return ()
    specs = sorted(
        (m for m in middlewares if m.backend == backend),
        key=lambda m: (m.order, m.name),
    )
    out: list[_Injection] = []
    for spec in specs:
        out.extend(renderer(spec, feature_key))
    return tuple(out)
