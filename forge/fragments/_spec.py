"""Fragment + FragmentImplSpec dataclasses + parity-tier helpers.

A **Fragment** describes how to apply a named template fragment (living
under ``forge/templates/_fragments/<name>/<backend>/``) to a generated
project. Fragments are internal plumbing: users never name them
directly. Users select **Options** (``forge/options/``); each Option
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
from typing import Literal

from forge.config import BackendLanguage
from forge.errors import FragmentError
from forge.middleware_spec import MiddlewareSpec

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
    # Epic E (1.1.0-alpha.1) — Option paths this implementation reads at
    # apply time. The resolver validates each entry against
    # OPTION_REGISTRY before generation begins, and FragmentContext.options
    # exposes only these paths to the fragment (no implicit access to the
    # whole option space). Fragments that don't need option values leave
    # this empty and see `ctx.options == {}`.
    reads_options: tuple[str, ...] = ()


ParityTier = Literal[1, 2, 3]
"""RFC-006 cross-backend parity tiers.

Tier 1: must land on every registered backend (Python, Node, Rust, plus
    any plugin-registered backends that forge ships support for). A new
    tier-1 fragment can't merge without an implementation for each.
Tier 2: best-effort — may land on a subset, with a documented migration
    path in RFC-006 for the backends that don't yet have it.
Tier 3: Python-only, explicitly scoped. Used for AI / RAG / LLM features
    whose Python SDK ecosystem has no Node / Rust equivalent. The CLI
    surfaces this so users picking a non-Python backend know upfront.

The parity tier is authoritative metadata — the tier must match the
keys of ``implementations``. ``tests/test_fragment_parity.py`` enforces
that: a tier-1 fragment missing a built-in backend implementation is
a hard CI failure; a tier-3 fragment shipping a Node implementation is
a tier bump, not a silent success.
"""


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
    # RFC-006 (Epic S, 1.1.0-alpha.1) — cross-backend parity tier. See
    # ``ParityTier`` above. Default ``None`` means "auto-derive from
    # ``implementations``": 1 if every built-in backend is covered, 3 if
    # only Python is covered, 2 otherwise. Authors override explicitly
    # when the auto-derivation would mis-label semantics (e.g. a Python-
    # only fragment that's a committed tier-2 migration target, not
    # permanent tier-3). After ``__post_init__`` the attribute is
    # guaranteed non-None so callers can treat it as a concrete tier.
    parity_tier: ParityTier | None = None
    # Epic K (1.1.0-alpha.1) — declarative middleware registrations. Each
    # spec targets one backend; a fragment that supports all three backends
    # ships three specs. At apply time, the applier expands every spec
    # targeting the current backend into ``_Injection`` records using the
    # per-backend renderer (``render_fastapi_middleware``,
    # ``render_fastify_plugin``, ``render_axum_layer``). Fragments that
    # don't register middleware leave this empty and behave as before.
    middlewares: tuple[MiddlewareSpec, ...] = ()

    def supports(self, language: BackendLanguage) -> bool:
        return language in self.implementations

    def __post_init__(self) -> None:
        """Epic I (1.1.0-alpha.1) — fragment self-consistency at construction.

        Catches the obvious ways a fragment can conflict with itself: a
        ``conflicts_with`` entry pointing at its own name, or a fragment
        listed in both ``depends_on`` and ``conflicts_with``. These are
        legitimate authoring mistakes; surfacing them at Fragment()
        construction beats surfacing them at resolve time in a generated
        project where the error context is thinner.

        Epic S (1.1.0-alpha.1) also auto-derives ``parity_tier`` when
        not explicitly set, so the vast majority of existing fragments
        don't need an edit. A tier that was explicitly declared is left
        alone — authors use that to assert "this is intentionally tier-
        2 pending migration" rather than the naive count-backends
        heuristic.
        """
        if self.name in self.conflicts_with:
            raise FragmentError(
                f"Fragment {self.name!r} lists itself in conflicts_with",
                context={"fragment": self.name, "conflicts_with": list(self.conflicts_with)},
            )
        overlap = set(self.depends_on) & set(self.conflicts_with)
        if overlap:
            raise FragmentError(
                f"Fragment {self.name!r} has names in both depends_on and "
                f"conflicts_with: {sorted(overlap)}",
                context={
                    "fragment": self.name,
                    "depends_on": list(self.depends_on),
                    "conflicts_with": list(self.conflicts_with),
                    "overlap": sorted(overlap),
                },
            )
        if self.parity_tier is None:
            object.__setattr__(self, "parity_tier", _auto_parity_tier(self.implementations))
        else:
            # Explicit tier — validate it agrees with the impls at
            # construction time. Tier-1 must cover all built-ins;
            # tier-3 must be Python-only. Tier-2 is the permissive
            # residual and is allowed to label any subset.
            _validate_explicit_parity_tier(self.name, self.parity_tier, self.implementations)


def _validate_explicit_parity_tier(
    name: str,
    tier: ParityTier,
    implementations: dict[BackendLanguage, FragmentImplSpec],
) -> None:
    """Enforce tier ↔ impl consistency when the author pins a tier.

    Raised at ``Fragment()`` construction so plugin authors see parity
    mismatches on plugin load rather than waiting for forge's own test
    suite (``tests/test_fragment_parity.py``) to run in CI.
    """
    built_ins = {BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST}
    covered = {lang for lang in implementations if lang in built_ins}

    if tier == 1 and covered != built_ins:
        missing = sorted(lang.value for lang in (built_ins - covered))
        raise FragmentError(
            f"Fragment {name!r} is tier 1 (cross-backend parity) but is "
            f"missing implementations for: {missing}",
            context={
                "fragment": name,
                "parity_tier": tier,
                "missing_backends": missing,
            },
        )
    if tier == 3 and covered != {BackendLanguage.PYTHON}:
        raise FragmentError(
            f"Fragment {name!r} is tier 3 (Python-only) but ships implementations "
            f"for: {sorted(c.value for c in covered)}",
            context={
                "fragment": name,
                "parity_tier": tier,
                "covered_backends": sorted(c.value for c in covered),
            },
        )


def _auto_parity_tier(
    implementations: dict[BackendLanguage, FragmentImplSpec],
) -> ParityTier:
    """Derive a :data:`ParityTier` from the implementations dict.

    - All three built-in backends present ⇒ **tier 1** (cross-backend
      parity target met).
    - Only Python present ⇒ **tier 3** (Python-only — honest scope for
      AI/RAG/LLM features whose ecosystem has no Node/Rust equivalent).
    - Any other mixture (Python + Node, Python + Rust, Node + Rust,
      etc.) ⇒ **tier 2** (best-effort — some backends are pending).

    Plugin-registered backends do not bump the tier: parity is measured
    against the three built-ins. A plugin fragment that supplies both
    a Python and a Go implementation (but no Node/Rust) is still tier
    2 — the built-in parity target is not yet met. This is a conscious
    choice so the tier's meaning stays stable across plugin registries.
    """
    built_ins = {BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST}
    present = {k for k in implementations if k in built_ins}
    if present == built_ins:
        return 1
    if present == {BackendLanguage.PYTHON}:
        return 3
    return 2
