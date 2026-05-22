"""Cross-language port-declaration spec (Pillar A.4, 1.3.0).

The second :class:`~forge.appliers.renderers.FragmentRenderer`
implementation after :class:`~forge.specs.middleware.MiddlewareSpec`
(Pillar A.2). Joins it as a declarative replacement for per-backend
``inject.yaml`` ceremony — specifically, the boilerplate every
``*_port`` fragment ships today: import the port interface, import
the adapter, wire the factory at the language's standard anchor.

The Pillar D ``llm_port`` Python + Node + Rust impls become ~10
lines of :class:`PortSpec` literals each instead of three
near-identical ``inject.yaml`` files. The first concrete consumer
lands in a separate PR (Pillar D.2); this PR ships only the spec
class + per-backend Jinja templates + tests.

Per-backend anchors + targets are modelled on the existing
``queue_port`` fragment (the canonical pre-PortSpec port shape):

  Python — ``src/app/core/container.py`` @ ``FORGE:APP_POST_CONFIGURE``
  Node   — ``src/app.ts`` @ ``FORGE:MIDDLEWARE_IMPORTS``
  Rust   — ``src/lib.rs`` @ ``FORGE:LIB_MOD_REGISTRATION``

Usage shape inside a fragment registration::

    register_fragment(
        Fragment(
            name="llm_port",
            order=80,
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir="llm_port/python",
                ),
            },
            renderers=(
                PortSpec(
                    name="llm",
                    backend=BackendLanguage.PYTHON,
                    interface_path="app/ports/llm.py",
                    adapter_imports=(
                        "OpenAiAdapter from app.adapters.llm.openai",
                    ),
                    service_factory=(
                        "from app.core.config import settings as _settings\\n"
                        "_llm_adapter = OpenAiAdapter(api_key=_settings.openai_api_key)"
                    ),
                ),
            ),
        )
    )
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from forge.config import BackendLanguage

if TYPE_CHECKING:
    import jinja2

    from forge.appliers.plan import InjectionZone, _Injection


# Templates ship under ``forge/templates/_shared/port_spec/<lang>.jinja``
# next to the RFC-009 service-registration macros. Resolved via the
# package-root ``Path`` rather than ``importlib.resources`` because the
# rest of forge already addresses templates that way (see
# ``forge/templates/_shared/service_registration/README.md``).
_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates" / "_shared" / "port_spec"


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortSpec:
    """One port declaration, targeting one backend.

    Implements the :class:`~forge.appliers.renderers.FragmentRenderer`
    protocol — :meth:`FragmentPlan.from_impl` accepts a tuple of any
    ``FragmentRenderer`` instances and dispatches each one's
    :meth:`render` uniformly. Sits next to :class:`MiddlewareSpec`
    as the second built-in implementation.

    Attributes:
        name: Fragment-scoped identifier (typically the port name —
            ``"llm"``, ``"queue"``, ``"rag"``). Used in
            ``FORGE:BEGIN`` / ``FORGE:END`` sentinels and as the
            ``(order, name)`` sort key in :func:`_render_all`.
        backend: Which backend this spec applies to. A port supporting
            Python + Node + Rust ships three specs, one per backend.
        interface_path: Module path of the port-interface module
            (e.g. ``"app/ports/llm.py"`` on Python,
            ``"app/ports/llm.ts"`` on Node,
            ``"src/ports/llm.rs"`` or ``"crate::ports::llm"`` on Rust).
            The per-backend Jinja template handles the language-
            specific massaging (slash → dot, ``.ts`` → ``.js``, mod
            decl derivation).
        adapter_imports: Modules / symbols the wiring needs imported.
            Shape per backend follows the existing per-backend
            ``inject.yaml`` conventions:
              * Python: ``("dotted.module",)`` or
                ``("Symbol from dotted.module",)``.
              * Node:   ``("Symbol from ./module/path",)`` or a bare
                ``("./module/path",)`` for a side-effect import.
              * Rust:   ``("crate::adapters::foo::Adapter",)`` —
                emitted as ``use <path>;``.
            Empty tuple is fine — a port that only re-exports its
            interface (the queue_port pre-adapter shape) carries no
            ``adapter_imports``.
        service_factory: The wiring statement(s) to emit at the
            anchor. Verbatim — multiline strings preserve their
            indentation. Typically an adapter instantiation
            (``_llm_adapter = OpenAiAdapter(...)``), a NestJS
            ``container.bind(...)`` registration, or an Axum
            ``.layer(Extension(...))`` clause. Empty string is fine
            for interface-only ports (e.g. ``queue_port`` with no
            concrete adapter selected — only the import lands).
        attach_zone: The injection zone every record this spec emits
            lands in. Defaults to ``"generated"`` — re-generation
            overwrites, matching the pre-Pillar-A behaviour. Pass
            ``"user"`` for ports the user is expected to hand-edit
            post-generation (alternate API base URLs, custom auth
            headers), or ``"merge"`` for three-way merge semantics.
        order: Insertion order. Lower renders earlier. Ports
            canonically order by "lower-level first": a port with
            ``port_dependencies`` set MUST have a strictly higher
            ``order`` than every entry in ``port_dependencies``, so
            its wiring lands after the deps it references. Defaults
            to 100 (the same neutral default as RFC-009
            ``ServiceRegistrationSpec``).
        port_dependencies: Other PortSpec names whose wiring this
            port references in its ``service_factory``. Currently
            advisory — :func:`detect_port_cycle` exposes a cycle
            detector that future ``Fragment``-level validation will
            use to fail at registration time. Plain tuple of strings
            (matching :attr:`name` of the upstream specs); no live
            object reference, so the validation stays scoped to
            a single fragment's renderers tuple.
    """

    name: str
    backend: BackendLanguage
    interface_path: str
    adapter_imports: tuple[str, ...] = ()
    service_factory: str = ""
    attach_zone: InjectionZone = "generated"
    order: int = 100
    port_dependencies: tuple[str, ...] = ()

    def render(
        self,
        *,
        backend: BackendLanguage,
        feature_key: str,
        jinja_env: jinja2.Environment | None = None,
    ) -> tuple[_Injection, ...]:
        """Emit injection records via the matching per-backend renderer.

        Returns ``()`` when ``backend`` doesn't match :attr:`backend`
        or when no renderer is registered for the requested backend
        (so a plugin-introduced language without a built-in renderer
        fails gracefully — matching :class:`MiddlewareSpec`).

        ``jinja_env`` is accepted for protocol parity with
        :class:`MiddlewareSpec`; PortSpec needs a Jinja environment
        to expand its per-backend templates, so it builds a private
        one when the caller doesn't pass one. The caller-provided
        env (when present) MUST resolve loader paths under
        ``forge/templates/_shared/port_spec/`` — the renderer reaches
        into it for template names like ``"python.jinja"``.
        """
        if backend != self.backend:
            return ()
        renderer = _RENDERERS.get(backend)
        if renderer is None:
            return ()
        env = jinja_env if jinja_env is not None else _default_jinja_env()
        return renderer(self, feature_key, env)


# ---------------------------------------------------------------------------
# Per-backend renderers — each produces a tuple of `_Injection` records.
# ---------------------------------------------------------------------------


def _fastapi_target() -> str:
    return "src/app/core/container.py"


def _fastapi_marker() -> str:
    return "FORGE:APP_POST_CONFIGURE"


def _fastify_target() -> str:
    return "src/app.ts"


def _fastify_marker() -> str:
    return "FORGE:MIDDLEWARE_IMPORTS"


def _axum_target() -> str:
    return "src/lib.rs"


def _axum_marker() -> str:
    return "FORGE:LIB_MOD_REGISTRATION"


def _default_jinja_env() -> jinja2.Environment:
    """Build the package-internal Jinja env for PortSpec templates.

    Constructed lazily per render call. The cost is negligible for
    the synth-injection volume PortSpec sees (one env per port per
    backend per fragment apply), and keeps the module import-free
    of Jinja for callers that never use PortSpec.
    """
    import jinja2  # noqa: PLC0415 — late import keeps the spec module pure-data

    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_ROOT)),
        autoescape=False,
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _render_template(env: jinja2.Environment, template_name: str, spec: PortSpec) -> str:
    """Load and render a per-backend port_spec macro.

    Each per-backend template defines a single ``snippet(port)``
    Jinja macro. The renderer imports the macro and calls it with
    a dict view of the spec — Jinja can't introspect dataclasses
    directly (no ``__getitem__``), and turning PortSpec into a
    Jinja-friendly mapping at the call site keeps the templates
    purely data-driven.
    """
    template = env.get_template(template_name)
    module = template.module
    snippet_macro: Callable[[dict[str, object]], str] = module.snippet  # type: ignore[attr-defined]
    port_view: dict[str, object] = {
        "name": spec.name,
        "interface_path": spec.interface_path,
        "adapter_imports": spec.adapter_imports,
        "service_factory": spec.service_factory,
    }
    rendered = str(snippet_macro(port_view))
    return rendered.rstrip("\n")


def render_fastapi_port(
    spec: PortSpec, feature_key: str, env: jinja2.Environment
) -> tuple[_Injection, ...]:
    """Emit _Injection records for a Python/FastAPI port wiring."""
    from forge.appliers.plan import _Injection  # noqa: PLC0415 — late import

    snippet = _render_template(env, "python.jinja", spec)
    return (
        _Injection(
            feature_key=feature_key,
            target=_fastapi_target(),
            marker=_fastapi_marker(),
            snippet=snippet,
            position="after",
            zone=spec.attach_zone,
        ),
    )


def render_fastify_port(
    spec: PortSpec, feature_key: str, env: jinja2.Environment
) -> tuple[_Injection, ...]:
    """Emit _Injection records for a Node/Fastify port wiring."""
    from forge.appliers.plan import _Injection  # noqa: PLC0415

    snippet = _render_template(env, "node.jinja", spec)
    return (
        _Injection(
            feature_key=feature_key,
            target=_fastify_target(),
            marker=_fastify_marker(),
            snippet=snippet,
            position="after",
            zone=spec.attach_zone,
        ),
    )


def render_axum_port(
    spec: PortSpec, feature_key: str, env: jinja2.Environment
) -> tuple[_Injection, ...]:
    """Emit _Injection records for a Rust/Axum port wiring."""
    from forge.appliers.plan import _Injection  # noqa: PLC0415

    snippet = _render_template(env, "rust.jinja", spec)
    return (
        _Injection(
            feature_key=feature_key,
            target=_axum_target(),
            marker=_axum_marker(),
            snippet=snippet,
            position="after",
            zone=spec.attach_zone,
        ),
    )


# Dispatch table. Adding a new backend (Go, Java, Elixir) = register a
# renderer here and ship a sibling ``<lang>.jinja`` template under
# ``forge/templates/_shared/port_spec/``.
_RENDERERS: dict[
    BackendLanguage,
    Callable[[PortSpec, str, jinja2.Environment], tuple[_Injection, ...]],
] = {
    BackendLanguage.PYTHON: render_fastapi_port,
    BackendLanguage.NODE: render_fastify_port,
    BackendLanguage.RUST: render_axum_port,
}


# ---------------------------------------------------------------------------
# Cycle detection — advisory helper for Fragment-level validation
# ---------------------------------------------------------------------------


def detect_port_cycle(ports: tuple[PortSpec, ...]) -> tuple[str, ...] | None:
    """Return the cycle path through ``port_dependencies`` if any, else ``None``.

    Single-fragment scope — the dependency graph is built from the
    ``name`` -> ``port_dependencies`` mapping inside ``ports`` only.
    Dependencies pointing at names not present in ``ports`` are
    treated as external (no edge) — this lets a fragment depend on
    a port that another fragment owns without us needing the global
    PortSpec registry that doesn't exist yet.

    Returns the offending cycle as a tuple of port names (first
    node repeated at the end) when detected, ``None`` otherwise.
    """
    known: dict[str, tuple[str, ...]] = {p.name: p.port_dependencies for p in ports}
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_path: list[str] = []

    def _walk(node: str, path: list[str]) -> bool:
        if node in visiting:
            # First time we re-encounter ``node``; trim ``path`` to start
            # at the cycle entry. ``path[-1]`` is the parent that re-cited
            # ``node``; ``path.index(node)`` is the original first sighting.
            start = path.index(node)
            cycle_path.extend(path[start:])
            cycle_path.append(node)
            return True
        if node in visited:
            return False
        visiting.add(node)
        path.append(node)
        for dep in known.get(node, ()):
            if dep not in known:
                # External dep — no edge, no cycle from here.
                continue
            if _walk(dep, path):
                return True
        path.pop()
        visiting.discard(node)
        visited.add(node)
        return False

    for port_name in known:
        if _walk(port_name, []):
            return tuple(cycle_path)
    return None
