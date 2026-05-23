"""Tests for the 1.2.0 fragment-DX cheap wins.

This file covers the public-surface contract for three small additions
to the fragment authoring API:

1. ``Fragment.shared_env_vars`` — backend-agnostic env vars declared
   once on the fragment instead of repeated per
   :class:`FragmentImplSpec.env_vars`.
2. ``Fragment.before`` / ``Fragment.after`` — declarative ordering
   constraints that complement numeric ``order``, soft-conditional on
   the neighbour also being in the plan.
3. Docstring sweep — the ``forge.feature_injector`` shim was deleted
   in 1.2.0-alpha.1; docstrings that still pointed at it are migrated
   to the post-shim home (``forge.sync.forge_to_project.updater`` for
   the orchestrator; ``forge.appliers.*`` for the body helpers).

The deeper end-to-end + cycle-detection coverage lives in
``tests/fragments/test_fragment_dx_fields.py``; this file is the
single-PR top-level surface used by the cheap-wins ship sequence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from forge.appliers.plan import FragmentPlan, _merge_env_vars
from forge.capability_resolver import _topo_sort
from forge.config import BackendLanguage
from forge.errors import FragmentError
from forge.fragments._registry import _FragmentRegistry
from forge.fragments._spec import Fragment, FragmentImplSpec

_FORGE_ROOT = Path(__file__).resolve().parent.parent / "forge"


# ---------------------------------------------------------------------------
# Item 1 — shared_env_vars
# ---------------------------------------------------------------------------


class TestSharedEnvVars:
    """Backend-agnostic env vars merge with per-impl env_vars at plan time."""

    def test_default_is_empty_tuple_preserves_old_behaviour(self):
        """A fragment without ``shared_env_vars`` looks identical to pre-1.2.0."""
        frag = Fragment(name="x", implementations={})
        assert frag.shared_env_vars == ()

    def test_registration_with_shared_env_vars_produces_merged_env_list(self, tmp_path: Path):
        """End-to-end: shared + per-impl combine on the resulting FragmentPlan."""
        frag_dir = tmp_path / "object_store"
        frag_dir.mkdir()
        impl = FragmentImplSpec(
            fragment_dir=str(frag_dir),
            env_vars=(("DATABASE_URL", "postgres://x"),),
        )
        plan = FragmentPlan.from_impl(
            impl,
            feature_key="object_store",
            shared_env_vars=(
                ("AWS_REGION", "us-east-1"),
                ("S3_ENDPOINT_URL", "http://s3:9000"),
            ),
        )
        assert plan.env_vars == (
            ("AWS_REGION", "us-east-1"),
            ("S3_ENDPOINT_URL", "http://s3:9000"),
            ("DATABASE_URL", "postgres://x"),
        )

    def test_per_impl_wins_on_collision(self):
        """A per-impl entry with the same key overrides the shared default."""
        merged = _merge_env_vars(
            (("AWS_REGION", "us-east-1"), ("AWS_PROFILE", "default")),
            (("AWS_REGION", "eu-west-1"),),
        )
        # AWS_REGION overridden; AWS_PROFILE survives from shared.
        assert merged == (
            ("AWS_PROFILE", "default"),
            ("AWS_REGION", "eu-west-1"),
        )

    def test_shared_only_no_per_impl_passes_through(self):
        merged = _merge_env_vars(
            (("AWS_REGION", "us-east-1"), ("S3_ENDPOINT_URL", "http://s3:9000")),
            (),
        )
        assert merged == (
            ("AWS_REGION", "us-east-1"),
            ("S3_ENDPOINT_URL", "http://s3:9000"),
        )

    def test_per_impl_only_no_shared_passes_through(self):
        merged = _merge_env_vars((), (("PG_HOST", "postgres"),))
        assert merged == (("PG_HOST", "postgres"),)

    def test_existing_callers_without_kwarg_unchanged(self, tmp_path: Path):
        """``FragmentPlan.from_impl`` default of ``shared_env_vars=()``
        means every pre-1.2.0 call site sees byte-identical output."""
        frag_dir = tmp_path / "redis_cache"
        frag_dir.mkdir()
        impl = FragmentImplSpec(
            fragment_dir=str(frag_dir),
            env_vars=(("REDIS_URL", "redis://localhost:6379"),),
        )
        plan = FragmentPlan.from_impl(impl, feature_key="redis_cache")
        assert plan.env_vars == (("REDIS_URL", "redis://localhost:6379"),)


# ---------------------------------------------------------------------------
# Item 2 — before / after declarative ordering
# ---------------------------------------------------------------------------


def _basic_impl(name: str, tmp_path: Path) -> FragmentImplSpec:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return FragmentImplSpec(fragment_dir=str(d))


def _seed_registry(monkeypatch: pytest.MonkeyPatch, frags: list[Fragment]) -> _FragmentRegistry:
    """Swap a fresh ``_FragmentRegistry`` into both import sites.

    Mirrors ``tests/fragments/test_fragment_dx_fields.py::_seed_registry``
    and ``tests/test_capability_resolver.py::isolated_registries``.
    """
    fake = _FragmentRegistry()
    for f in frags:
        fake[f.name] = f
    monkeypatch.setattr("forge.capability_resolver.FRAGMENT_REGISTRY", fake)
    monkeypatch.setattr("forge.fragments._registry.FRAGMENT_REGISTRY", fake)
    return fake


class TestBeforeAfterOrdering:
    """``before`` / ``after`` flow through the resolver toposort and audit."""

    def test_defaults_are_empty_tuples(self):
        frag = Fragment(name="x", implementations={})
        assert frag.before == ()
        assert frag.after == ()

    def test_before_orders_self_ahead_of_target(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """Fragment A with ``before=("B",)`` orders before B."""
        a = Fragment(
            name="a",
            implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
            before=("b",),
        )
        b = Fragment(
            name="b",
            implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
        )
        _seed_registry(monkeypatch, [a, b])
        assert _topo_sort({"a", "b"}) == ["a", "b"]

    def test_after_orders_self_behind_target(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Fragment B with ``after=("A",)`` orders after A."""
        a = Fragment(
            name="a",
            implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
        )
        b = Fragment(
            name="b",
            implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
            after=("a",),
        )
        _seed_registry(monkeypatch, [a, b])
        assert _topo_sort({"a", "b"}) == ["a", "b"]

    def test_conflicting_before_and_after_raises_cycle_error(self, tmp_path: Path):
        """A direct before/after cycle is caught at registry freeze with the cycle path."""
        fake = _FragmentRegistry()
        fake["a"] = Fragment(
            name="a",
            implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
            before=("b",),
        )
        fake["b"] = Fragment(
            name="b",
            implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
            before=("a",),  # cycle: a→b→a
        )
        with pytest.raises(FragmentError) as exc:
            fake.freeze()
        assert "Cyclic dependencies detected" in str(exc.value)
        # The DFS should surface the actual cycle path in error context.
        assert exc.value.context.get("cycle_path"), (
            f"cycle_path missing from FragmentError.context: {exc.value.context}"
        )

    def test_overlap_of_before_and_after_rejected_at_construction(self):
        """A fragment listing the same neighbour in both ``before`` and
        ``after`` is logically impossible; rejected by ``__post_init__``."""
        with pytest.raises(FragmentError, match="both before and"):
            Fragment(name="a", implementations={}, before=("b",), after=("b",))

    def test_self_reference_in_before_rejected(self):
        with pytest.raises(FragmentError, match="lists itself in before"):
            Fragment(name="a", implementations={}, before=("a",))

    def test_self_reference_in_after_rejected(self):
        with pytest.raises(FragmentError, match="lists itself in after"):
            Fragment(name="a", implementations={}, after=("a",))

    def test_numeric_order_tiebreaks_when_no_before_after(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """``order`` still tiebreaks fragments without explicit constraints."""
        high = Fragment(
            name="high",
            implementations={BackendLanguage.PYTHON: _basic_impl("high", tmp_path)},
            order=200,
        )
        low = Fragment(
            name="low",
            implementations={BackendLanguage.PYTHON: _basic_impl("low", tmp_path)},
            order=10,
        )
        _seed_registry(monkeypatch, [high, low])
        assert _topo_sort({"high", "low"}) == ["low", "high"]

    def test_before_after_compose_with_numeric_order(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """``before``/``after`` edges dominate; ``order`` tiebreaks within a layer."""
        # 'a' must precede both 'b' and 'c' via before-edge.
        # Within the remaining {b, c}, numeric order tiebreaks → low order first.
        a = Fragment(
            name="a",
            implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
            before=("b", "c"),
            order=999,  # high — but the before-edge wins.
        )
        b = Fragment(
            name="b",
            implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
            order=200,
        )
        c = Fragment(
            name="c",
            implementations={BackendLanguage.PYTHON: _basic_impl("c", tmp_path)},
            order=50,
        )
        _seed_registry(monkeypatch, [a, b, c])
        order = _topo_sort({"a", "b", "c"})
        # 'a' first (before-edge), then c (order=50) before b (order=200).
        assert order == ["a", "c", "b"]

    def test_before_is_soft_when_neighbour_absent_from_plan(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """Unlike ``depends_on``, ``before`` does NOT pull the target in."""
        a = Fragment(
            name="a",
            implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
            before=("absent_neighbour",),
        )
        _seed_registry(monkeypatch, [a])
        assert _topo_sort({"a"}) == ["a"]


# ---------------------------------------------------------------------------
# Item 3 — feature_injector shim references
# ---------------------------------------------------------------------------


class TestNoFeatureInjectorReferences:
    """The ``forge.feature_injector`` shim was deleted in 1.2.0-alpha.1.

    Docstrings + comments that still point at it are stale and confuse
    plugin authors looking for the post-shim entry points. This test
    enforces that the in-scope fix set stays clean across future edits.

    Out-of-scope files: ``forge/sync/**`` and ``forge/capability_resolver.py``
    are owned by a separate workstream (sync rewrite + resolver
    refactor) — their references are tracked in the 1.2.0-beta cleanup
    backlog, not here. The exemption is explicit + finite so a new
    ``forge/`` file accidentally re-introducing the reference still
    fails this test.
    """

    # Files that legitimately still reference the shim and are owned
    # by other workstreams. Each entry must include the rationale.
    _EXEMPT_RELATIVE_PATHS: frozenset[str] = frozenset(
        {
            # Sync rewrite (1.2.0-beta) will resurface these as part of
            # its own docstring sweep — out of scope for the cheap-wins PR.
            "sync/project_to_forge/apply_bundle/_shared.py",
            "sync/project_to_forge/harvester/_orchestrator.py",
            # Resolver refactor (Pillar B) owns the ResolvedFeature shim
            # docstrings — they'll be removed together with the shim itself.
            "capability_resolver.py",
        }
    )

    # Word-boundary match so the substring isn't found inside an
    # unrelated identifier; case-sensitive because the symbol was.
    _PATTERN = re.compile(r"\bfeature_injector\b")

    def test_no_stale_shim_references_in_touched_files(self):
        offenders: list[tuple[Path, int, str]] = []
        for py_file in _FORGE_ROOT.rglob("*.py"):
            rel = py_file.relative_to(_FORGE_ROOT).as_posix()
            if rel in self._EXEMPT_RELATIVE_PATHS:
                continue
            for lineno, line in enumerate(
                py_file.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if self._PATTERN.search(line):
                    offenders.append((py_file, lineno, line.rstrip()))
        if offenders:
            rendered = "\n".join(
                f"  {p.relative_to(_FORGE_ROOT.parent)}:{ln}: {body}" for p, ln, body in offenders
            )
            raise AssertionError(
                "Found stale ``forge.feature_injector`` references in files "
                "that should have been migrated by the 1.2.0 cheap-wins "
                "docstring sweep. Migrate to:\n"
                "  * Orchestrator: ``forge.sync.forge_to_project.updater``\n"
                "  * Body helpers: ``forge.appliers.*`` (plan/injection/files/deps)\n"
                "  * Injectors:    ``forge.injectors.*`` / ``forge.appliers.injection``\n"
                f"Offending lines:\n{rendered}\n\n"
                "If this is a deliberate new reference in an out-of-scope "
                "file, add it to ``_EXEMPT_RELATIVE_PATHS`` with a rationale."
            )

    def test_exempt_paths_still_exist(self):
        """Guard against the exempt list drifting after a file rename.

        Without this check, a sync rewrite that renames the exempt files
        would silently turn the previous test into a no-op for the
        renamed code path.
        """
        for rel in self._EXEMPT_RELATIVE_PATHS:
            assert (_FORGE_ROOT / rel).is_file(), (
                f"Exempt path {rel!r} no longer exists under forge/. "
                "Remove it from ``_EXEMPT_RELATIVE_PATHS`` or update the "
                "entry to point at the renamed file."
            )
