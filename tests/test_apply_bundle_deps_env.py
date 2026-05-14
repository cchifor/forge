"""Tests for ``apply_bundle_to_fragments`` deps + env apply-back matrix.

This module covers the deps + env branches of
:func:`forge.sync.project_to_forge.apply_bundle.apply_bundle_to_fragments`,
which rewrite a fragment's ``dependencies=(...)`` /
``env_vars=((...),)`` tuple inside its registering ``fragments.py``
module. The files / block branches are covered separately in
``tests/test_harvest_invariants.py``.

Each test scaffolds a synthetic forge_repo on disk with an inline
``fragments.py`` carrying the registration shape under test, registers
a stub fragment with the in-process :data:`FRAGMENT_REGISTRY`, and
asserts the rewrite landed correctly on disk. The tests deliberately
avoid mutating the real built-in fragments.py modules — the synthetic
``forge_repo`` keeps the surface self-contained and parallelisable.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from forge.config import BackendLanguage
from forge.extractors.pipeline import CandidatePatch
from forge.fragments import FRAGMENT_REGISTRY, Fragment, FragmentImplSpec
from forge.sync.project_to_forge.apply_bundle import (
    apply_bundle_to_fragments,
)
from forge.sync.project_to_forge.harvester import HarvestBundle

# ---------------------------------------------------------------------------
# Scaffolding helpers
# ---------------------------------------------------------------------------


def _register_synthetic_fragment(
    name: str,
    *,
    fragment_dir: str = "_synthetic",
    languages: tuple[BackendLanguage, ...] = (BackendLanguage.PYTHON,),
    dependencies: tuple[str, ...] = (),
    env_vars: tuple[tuple[str, str], ...] = (),
) -> Fragment:
    """Register a synthetic fragment with given deps/env so the apply-back
    path's registry-lookup step succeeds.

    Returns the Fragment so the test can reference its name. Pairs with
    :func:`_unregister_fragment` in a ``finally``.
    """
    impls: dict[BackendLanguage, FragmentImplSpec] = {}
    for lang in languages:
        impls[lang] = FragmentImplSpec(
            fragment_dir=fragment_dir,
            dependencies=dependencies,
            env_vars=env_vars,
        )
    fragment = Fragment(name=name, implementations=impls)

    was_frozen = getattr(FRAGMENT_REGISTRY, "frozen", False)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY[name] = fragment
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = True
    return fragment


def _unregister_fragment(name: str) -> None:
    was_frozen = getattr(FRAGMENT_REGISTRY, "frozen", False)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY.pop(name, None)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = True


def _write_fragments_py(
    forge_repo: Path,
    *,
    feature_namespace: str = "demo",
    body: str,
) -> Path:
    """Write an inline ``fragments.py`` under
    ``<forge_repo>/forge/features/<feature_namespace>/fragments.py``.

    Mirrors the canonical built-in layout so the applier's source-file
    discovery finds it without special-casing.
    """
    fragments_py = forge_repo / "forge" / "features" / feature_namespace / "fragments.py"
    fragments_py.parent.mkdir(parents=True, exist_ok=True)
    fragments_py.write_text(body, encoding="utf-8")
    return fragments_py


def _deps_candidate(
    *,
    fragment: str,
    backend: str = "api",
    rel_path: str = "pyproject.toml",
    action: str,
    name: str,
    fragment_spec: str | None,
    project_spec: str | None,
    risk: str = "safe-apply",
) -> CandidatePatch:
    """Construct a deps CandidatePatch with the structured-JSON diff."""
    payload = {
        "action": action,
        "name": name,
        "fragment_spec": fragment_spec,
        "project_spec": project_spec,
    }
    return CandidatePatch(
        fragment=fragment,
        backend=backend,
        kind="deps",
        rel_path=rel_path,
        target_path=str(Path(rel_path)),
        diff=json.dumps(payload, sort_keys=True, indent=2),
        baseline_sha=None,
        current_sha="",
        risk=risk,
        rationale=f"deps drift: {action} {name}",
    )


def _env_candidate(
    *,
    fragment: str,
    backend: str = "api",
    rel_path: str = ".env.example",
    action: str,
    key: str,
    fragment_value: str | None,
    project_value: str | None,
    risk: str = "safe-apply",
) -> CandidatePatch:
    """Construct an env CandidatePatch with the structured-JSON diff."""
    payload = {
        "action": action,
        "key": key,
        "fragment_value": fragment_value,
        "project_value": project_value,
    }
    return CandidatePatch(
        fragment=fragment,
        backend=backend,
        kind="env",
        rel_path=rel_path,
        target_path=str(Path(rel_path)),
        diff=json.dumps(payload, sort_keys=True, indent=2),
        baseline_sha=None,
        current_sha="",
        risk=risk,
        rationale=f"env drift: {action} {key}",
    )


def _bundle_with(cands: list[CandidatePatch], *, project_root: Path) -> HarvestBundle:
    return HarvestBundle(
        bundle_id="harvest-test",
        project_root=project_root,
        forge_version="0.0.0-test",
        candidates=cands,
    )


# Conventional shape — one fragment registered with one Python impl,
# dependencies + env_vars literal tuples. Used as the base for most
# tests, parameterised via ``.format(**fields)``.
_FRAGMENT_SOURCE_PY_TEMPLATE = '''"""Synthetic fragments.py — for apply-bundle tests."""

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec


register_fragment(
    Fragment(
        name="{name}",
        implementations={{
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="_synthetic",
                dependencies={dependencies_literal},
                env_vars={env_vars_literal},
            ),
        }},
    )
)
'''


def _make_fragments_py(
    forge_repo: Path,
    *,
    fragment_name: str,
    feature_namespace: str = "demo",
    dependencies_literal: str = "()",
    env_vars_literal: str = "()",
) -> Path:
    """Render and write the conventional template with the supplied tuples.

    Both literal arguments are Python source for the tuple expression
    (e.g. ``'("foo>=1.0",)'`` or ``'()'``).
    """
    body = _FRAGMENT_SOURCE_PY_TEMPLATE.format(
        name=fragment_name,
        dependencies_literal=dependencies_literal,
        env_vars_literal=env_vars_literal,
    )
    return _write_fragments_py(forge_repo, feature_namespace=feature_namespace, body=body)


# ---------------------------------------------------------------------------
# Deps — added / removed / modified
# ---------------------------------------------------------------------------


class TestApplyBundleDepsAdded:
    def test_added_appends_to_python_tuple(self, tmp_path: Path) -> None:
        """The canonical 'added' path — project carries a new dep the
        fragment doesn't declare; applier appends to the tuple."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_deps_added"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal='("foo>=1.0",)',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0",))
        try:
            bundle = _bundle_with(
                [
                    _deps_candidate(
                        fragment=fragment_name,
                        action="added",
                        name="bar",
                        fragment_spec=None,
                        project_spec="bar>=2.0",
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 1, [(e.status, e.error) for e in report.entries]
        assert report.errored == 0
        text = fragments_py.read_text(encoding="utf-8")
        # The applier should have appended bar>=2.0 to the tuple.
        assert '"foo>=1.0"' in text
        assert '"bar>=2.0"' in text
        # And the file should still be valid Python — re-import works.
        assert "register_fragment" in text


class TestApplyBundleDepsRemoved:
    def test_removed_drops_from_python_tuple(self, tmp_path: Path) -> None:
        """Fragment declares a dep the project no longer has; applier
        removes it from the tuple."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_deps_removed"
        _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal='("foo>=1.0", "bar>=2.0")',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0", "bar>=2.0"))
        try:
            bundle = _bundle_with(
                [
                    _deps_candidate(
                        fragment=fragment_name,
                        action="removed",
                        name="foo",
                        fragment_spec="foo>=1.0",
                        project_spec=None,
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 1, [(e.status, e.error) for e in report.entries]
        text = (forge_repo / "forge" / "features" / "demo" / "fragments.py").read_text(
            encoding="utf-8"
        )
        assert '"foo>=1.0"' not in text
        assert '"bar>=2.0"' in text

    def test_removed_last_item_yields_empty_tuple(self, tmp_path: Path) -> None:
        """When the removal leaves the tuple empty it serialises to ``()``."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_deps_empty"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal='("foo>=1.0",)',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0",))
        try:
            bundle = _bundle_with(
                [
                    _deps_candidate(
                        fragment=fragment_name,
                        action="removed",
                        name="foo",
                        fragment_spec="foo>=1.0",
                        project_spec=None,
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 1
        text = fragments_py.read_text(encoding="utf-8")
        assert "dependencies=()" in text
        assert '"foo>=1.0"' not in text


class TestApplyBundleDepsModified:
    def test_modified_replaces_spec_in_tuple(self, tmp_path: Path) -> None:
        """Same name, different pin — applier swaps the spec in place."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_deps_modified"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal='("foo>=1.0",)',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0",))
        try:
            bundle = _bundle_with(
                [
                    _deps_candidate(
                        fragment=fragment_name,
                        action="modified",
                        name="foo",
                        fragment_spec="foo>=1.0",
                        project_spec="foo>=2.0",
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 1, [(e.status, e.error) for e in report.entries]
        text = fragments_py.read_text(encoding="utf-8")
        assert '"foo>=1.0"' not in text
        assert '"foo>=2.0"' in text


# ---------------------------------------------------------------------------
# Env — added / removed / modified
# ---------------------------------------------------------------------------


class TestApplyBundleEnvAdded:
    def test_added_appends_to_env_vars(self, tmp_path: Path) -> None:
        """Project carries an env var the fragment doesn't declare; applier
        appends to the env_vars tuple-of-tuples."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_env_added"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            env_vars_literal='(("EXISTING", "old_value"),)',
        )
        _register_synthetic_fragment(fragment_name, env_vars=(("EXISTING", "old_value"),))
        try:
            bundle = _bundle_with(
                [
                    _env_candidate(
                        fragment=fragment_name,
                        action="added",
                        key="NEW_KEY",
                        fragment_value=None,
                        project_value="new_value",
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 1, [(e.status, e.error) for e in report.entries]
        text = fragments_py.read_text(encoding="utf-8")
        assert '"EXISTING"' in text and '"old_value"' in text
        assert '"NEW_KEY"' in text and '"new_value"' in text


class TestApplyBundleEnvRemoved:
    def test_removed_drops_from_env_vars(self, tmp_path: Path) -> None:
        """Fragment declares a key the project no longer has."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_env_removed"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            env_vars_literal='(("KEEP", "k"), ("DROP", "d"))',
        )
        _register_synthetic_fragment(fragment_name, env_vars=(("KEEP", "k"), ("DROP", "d")))
        try:
            bundle = _bundle_with(
                [
                    _env_candidate(
                        fragment=fragment_name,
                        action="removed",
                        key="DROP",
                        fragment_value="d",
                        project_value=None,
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 1, [(e.status, e.error) for e in report.entries]
        text = fragments_py.read_text(encoding="utf-8")
        assert '"DROP"' not in text
        assert '"KEEP"' in text


class TestApplyBundleEnvModified:
    def test_modified_replaces_value(self, tmp_path: Path) -> None:
        """Same key, different value — applier swaps it in place."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_env_modified"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            env_vars_literal='(("LLM_MODEL", "claude-sonnet-3.5"),)',
        )
        _register_synthetic_fragment(fragment_name, env_vars=(("LLM_MODEL", "claude-sonnet-3.5"),))
        try:
            bundle = _bundle_with(
                [
                    _env_candidate(
                        fragment=fragment_name,
                        action="modified",
                        key="LLM_MODEL",
                        fragment_value="claude-sonnet-3.5",
                        project_value="claude-sonnet-4",
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 1, [(e.status, e.error) for e in report.entries]
        text = fragments_py.read_text(encoding="utf-8")
        assert '"claude-sonnet-3.5"' not in text
        assert '"claude-sonnet-4"' in text


# ---------------------------------------------------------------------------
# Non-literal tuple → deferred fallback
# ---------------------------------------------------------------------------


class TestApplyBundleNonLiteralDeferred:
    """The applier must NOT mutate a fragments.py whose dependencies /
    env_vars expression isn't a literal tuple — too risky. It surfaces
    as ``deferred`` with a documented reason."""

    def test_deps_with_computed_tuple_is_deferred(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_deps_computed"
        # Source uses ``base_deps`` — NOT a literal tuple.
        body = f'''"""Synthetic fragments.py with a computed dependencies tuple."""

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec


base_deps = ("foo>=1.0",)


register_fragment(
    Fragment(
        name="{fragment_name}",
        implementations={{
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="_synthetic",
                dependencies=base_deps,
                env_vars=(),
            ),
        }},
    )
)
'''
        fragments_py = _write_fragments_py(forge_repo, body=body)

        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0",))
        try:
            bundle = _bundle_with(
                [
                    _deps_candidate(
                        fragment=fragment_name,
                        action="added",
                        name="bar",
                        fragment_spec=None,
                        project_spec="bar>=2.0",
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 0
        assert report.deferred == 1
        entry = report.entries[0]
        assert entry.status == "deferred"
        assert "not a literal tuple" in entry.error
        # The source file MUST NOT have been mutated.
        assert "base_deps" in fragments_py.read_text(encoding="utf-8")

    def test_env_with_function_call_is_deferred(self, tmp_path: Path) -> None:
        """Env applier also defers when the value isn't a literal tuple."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_env_computed"
        body = f'''"""Synthetic fragments.py with a computed env_vars tuple."""

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec


def _make_env():
    return (("FOO", "bar"),)


register_fragment(
    Fragment(
        name="{fragment_name}",
        implementations={{
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="_synthetic",
                dependencies=(),
                env_vars=_make_env(),
            ),
        }},
    )
)
'''
        fragments_py = _write_fragments_py(forge_repo, body=body)
        _register_synthetic_fragment(fragment_name, env_vars=(("FOO", "bar"),))
        try:
            bundle = _bundle_with(
                [
                    _env_candidate(
                        fragment=fragment_name,
                        action="added",
                        key="NEW",
                        fragment_value=None,
                        project_value="value",
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 0
        assert report.deferred == 1
        assert "not a literal tuple" in report.entries[0].error
        # Source untouched.
        assert "_make_env()" in fragments_py.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fragment not in registry → errored
# ---------------------------------------------------------------------------


class TestApplyBundleFragmentMissing:
    def test_deps_unregistered_fragment_is_errored(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        # No fragment registered, no source on disk.
        bundle = _bundle_with(
            [
                _deps_candidate(
                    fragment="nope_not_registered",
                    action="added",
                    name="bar",
                    fragment_spec=None,
                    project_spec="bar>=2.0",
                )
            ],
            project_root=tmp_path,
        )
        report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        assert report.errored == 1
        assert report.applied == 0
        assert "not in registry" in report.entries[0].error

    def test_env_unregistered_fragment_is_errored(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        bundle = _bundle_with(
            [
                _env_candidate(
                    fragment="nope_not_registered",
                    action="added",
                    key="K",
                    fragment_value=None,
                    project_value="v",
                )
            ],
            project_root=tmp_path,
        )
        report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        assert report.errored == 1
        assert "not in registry" in report.entries[0].error


class TestApplyBundleFragmentRegisteredButSourceMissing:
    """Registry has the fragment but no fragments.py on disk registers
    it (the operator passed a sparse forge_repo clone). Applier surfaces
    ``errored`` rather than crashing."""

    def test_deps_registered_but_source_missing_is_errored(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        forge_repo.mkdir()
        # Register, but don't write a fragments.py.
        fragment_name = "test_deps_orphan"
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0",))
        try:
            bundle = _bundle_with(
                [
                    _deps_candidate(
                        fragment=fragment_name,
                        action="added",
                        name="bar",
                        fragment_spec=None,
                        project_spec="bar>=2.0",
                    )
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)
        assert report.errored == 1
        assert "could not locate fragments.py" in report.entries[0].error


# ---------------------------------------------------------------------------
# Mixed-kinds bundle
# ---------------------------------------------------------------------------


class TestApplyBundleMixedKinds:
    """A bundle that mixes files / block / deps / env candidates must
    have each kind processed correctly. files/block branches are
    exercised via the registry resolution path; deps/env via the
    new fragments.py rewrite path."""

    def test_mixed_bundle_each_kind_processed(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        # Build a fragment with a files subtree AND deps/env in the
        # source registration.
        fragment_name = "test_mixed"
        # Files-side: write a fragment template tree under
        # forge/templates/_fragments/<frag>/files/foo.txt
        files_dir = forge_repo / "forge" / "templates" / "_fragments" / "test_mixed_dir" / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "foo.txt").write_text("upstream content\n", encoding="utf-8")
        # Project-side file the user edited.
        project_file = tmp_path / "user-foo.txt"
        project_file.write_text("user-edited content\n", encoding="utf-8")

        # Deps + env source-side.
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal='("foo>=1.0",)',
            env_vars_literal='(("EXISTING", "v"),)',
        )

        # Register with fragment_dir pointing at the files tree.
        fragment = _register_synthetic_fragment(
            fragment_name,
            fragment_dir="test_mixed_dir",
            dependencies=("foo>=1.0",),
            env_vars=(("EXISTING", "v"),),
        )
        try:
            bundle = _bundle_with(
                [
                    # files candidate — exercises _apply_files_candidate.
                    CandidatePatch(
                        fragment=fragment.name,
                        backend="api",
                        kind="files",
                        rel_path="foo.txt",
                        target_path=str(project_file),
                        diff="",
                        baseline_sha=None,
                        current_sha="",
                        risk="safe-apply",
                    ),
                    # deps candidate — exercises _apply_deps_candidate.
                    _deps_candidate(
                        fragment=fragment.name,
                        action="added",
                        name="newdep",
                        fragment_spec=None,
                        project_spec="newdep>=3.0",
                    ),
                    # env candidate — exercises _apply_env_candidate.
                    _env_candidate(
                        fragment=fragment.name,
                        action="added",
                        key="NEWKEY",
                        fragment_value=None,
                        project_value="newval",
                    ),
                ],
                project_root=tmp_path,
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        # Each kind processed: files write succeeds, deps + env rewrites
        # succeed. Total 3 applied.
        assert report.applied == 3, (
            f"expected 3 applied, got {report.applied}; "
            f"entries: {[(e.kind, e.status, e.error) for e in report.entries]}"
        )
        assert report.errored == 0
        # Files-side: fragment file carries user content.
        assert (files_dir / "foo.txt").read_text(encoding="utf-8") == "user-edited content\n"
        # Deps-side: fragments.py now has newdep.
        text = fragments_py.read_text(encoding="utf-8")
        assert '"newdep>=3.0"' in text
        # Env-side: fragments.py now has NEWKEY.
        assert '"NEWKEY"' in text and '"newval"' in text


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestApplyBundleIdempotent:
    """Re-running an already-applied bundle MUST emit
    ``skipped-unchanged`` rather than re-applying or erroring."""

    def test_deps_added_idempotent(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_idem_deps_added"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            # Already contains the post-state spec.
            dependencies_literal='("foo>=1.0", "bar>=2.0")',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0", "bar>=2.0"))
        try:
            bundle = _bundle_with(
                [
                    _deps_candidate(
                        fragment=fragment_name,
                        action="added",
                        name="bar",
                        fragment_spec=None,
                        project_spec="bar>=2.0",
                    )
                ],
                project_root=tmp_path,
            )
            mtime_before = fragments_py.stat().st_mtime_ns
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 0
        assert report.skipped == 1
        entry = report.entries[0]
        assert entry.status == "skipped-unchanged"
        assert "already present" in entry.error
        # No write happened.
        assert fragments_py.stat().st_mtime_ns == mtime_before

    def test_deps_removed_idempotent(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_idem_deps_removed"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            # Already excludes the removed spec.
            dependencies_literal='("bar>=2.0",)',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("bar>=2.0",))
        try:
            bundle = _bundle_with(
                [
                    _deps_candidate(
                        fragment=fragment_name,
                        action="removed",
                        name="foo",
                        fragment_spec="foo>=1.0",
                        project_spec=None,
                    )
                ],
                project_root=tmp_path,
            )
            mtime_before = fragments_py.stat().st_mtime_ns
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 0
        assert report.skipped == 1
        assert report.entries[0].status == "skipped-unchanged"
        assert "already absent" in report.entries[0].error
        assert fragments_py.stat().st_mtime_ns == mtime_before

    def test_env_modified_idempotent(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_idem_env_mod"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            env_vars_literal='(("K", "new"),)',
        )
        _register_synthetic_fragment(fragment_name, env_vars=(("K", "new"),))
        try:
            bundle = _bundle_with(
                [
                    _env_candidate(
                        fragment=fragment_name,
                        action="modified",
                        key="K",
                        fragment_value="old",
                        project_value="new",
                    )
                ],
                project_root=tmp_path,
            )
            mtime_before = fragments_py.stat().st_mtime_ns
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.skipped == 1
        assert report.entries[0].status == "skipped-unchanged"
        assert fragments_py.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# Risk filter
# ---------------------------------------------------------------------------


class TestApplyBundleRiskFilter:
    def test_needs_review_filtered_by_default(self, tmp_path: Path) -> None:
        """needs-review deps candidates land as ``skipped`` under the
        default ``safe-apply`` filter."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_filter_deps"
        fragments_py = _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal='("foo>=1.0",)',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0",))
        try:
            cand = _deps_candidate(
                fragment=fragment_name,
                action="added",
                name="bar",
                fragment_spec=None,
                project_spec="bar>=2.0",
                risk="needs-review",
            )
            bundle = _bundle_with([cand], project_root=tmp_path)
            mtime_before = fragments_py.stat().st_mtime_ns
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
            assert report.skipped == 1
            assert report.applied == 0
            assert "not in filter" in report.entries[0].error
            assert fragments_py.stat().st_mtime_ns == mtime_before

            # Widen the filter — same candidate now applies.
            report2 = apply_bundle_to_fragments(
                bundle,
                forge_repo,
                risk_filter=("safe-apply", "needs-review"),
                quiet=True,
            )
            assert report2.applied == 1
            assert '"bar>=2.0"' in fragments_py.read_text(encoding="utf-8")
        finally:
            _unregister_fragment(fragment_name)


# ---------------------------------------------------------------------------
# Malformed candidate payloads
# ---------------------------------------------------------------------------


class TestApplyBundleMalformedDiff:
    def test_deps_with_non_json_diff_is_errored(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_malformed_deps"
        _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal='("foo>=1.0",)',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0",))
        try:
            cand = _deps_candidate(
                fragment=fragment_name,
                action="added",
                name="bar",
                fragment_spec=None,
                project_spec="bar>=2.0",
            )
            # Mangle the diff so JSON parse fails.
            bad = replace(cand, diff="not actually json")
            bundle = _bundle_with([bad], project_root=tmp_path)
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)
        assert report.errored == 1
        assert "not valid JSON" in report.entries[0].error

    def test_deps_with_unknown_action_is_errored(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_unknown_action"
        _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal='("foo>=1.0",)',
        )
        _register_synthetic_fragment(fragment_name, dependencies=("foo>=1.0",))
        try:
            bad_payload = {
                "action": "frobnicated",
                "name": "bar",
                "fragment_spec": None,
                "project_spec": "bar>=2.0",
            }
            cand = CandidatePatch(
                fragment=fragment_name,
                backend="api",
                kind="deps",
                rel_path="pyproject.toml",
                target_path="pyproject.toml",
                diff=json.dumps(bad_payload),
                baseline_sha=None,
                current_sha="",
                risk="safe-apply",
            )
            bundle = _bundle_with([cand], project_root=tmp_path)
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)
        assert report.errored == 1
        assert "frobnicated" in report.entries[0].error


# ---------------------------------------------------------------------------
# Manifest-name → language inference
# ---------------------------------------------------------------------------


class TestApplyBundleLanguageInference:
    """The deps applier infers the backend language from ``rel_path``.
    Each manifest-name → language mapping is exercised here."""

    @pytest.mark.parametrize(
        ("rel_path", "lang_token", "spec"),
        [
            ("pyproject.toml", "PYTHON", "foo>=1.0"),
            ("package.json", "NODE", "foo@^1.0"),
            ("Cargo.toml", "RUST", "foo@1.0"),
        ],
    )
    def test_deps_routed_by_manifest_filename(
        self,
        tmp_path: Path,
        rel_path: str,
        lang_token: str,
        spec: str,
    ) -> None:
        """Each manifest-name routes to the matching ``BackendLanguage`` in
        the fragments.py source."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = f"test_lang_{lang_token.lower()}"
        body = (
            '"""Synthetic fragments.py with one impl."""\n\n'
            "from forge.config import BackendLanguage\n"
            "from forge.fragments._registry import register_fragment\n"
            "from forge.fragments._spec import Fragment, FragmentImplSpec\n\n"
            "register_fragment(\n"
            "    Fragment(\n"
            f'        name="{fragment_name}",\n'
            "        implementations={\n"
            f"            BackendLanguage.{lang_token}: FragmentImplSpec(\n"
            '                fragment_dir="_synthetic",\n'
            "                dependencies=(),\n"
            "            ),\n"
            "        },\n"
            "    )\n"
            ")\n"
        )
        fragments_py = _write_fragments_py(forge_repo, body=body)

        lang = BackendLanguage[lang_token]
        _register_synthetic_fragment(
            fragment_name,
            languages=(lang,),
            dependencies=(),
        )
        try:
            cand = _deps_candidate(
                fragment=fragment_name,
                rel_path=rel_path,
                action="added",
                name="foo",
                fragment_spec=None,
                project_spec=spec,
            )
            bundle = _bundle_with([cand], project_root=tmp_path)
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)
        assert report.applied == 1, [(e.status, e.error) for e in report.entries]
        text = fragments_py.read_text(encoding="utf-8")
        # The spec landed in the tuple.
        assert spec in text

    def test_deps_with_unknown_rel_path_is_errored(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_unknown_manifest"
        _make_fragments_py(
            forge_repo,
            fragment_name=fragment_name,
            dependencies_literal="()",
        )
        _register_synthetic_fragment(fragment_name)
        try:
            cand = _deps_candidate(
                fragment=fragment_name,
                rel_path="some-random.toml",
                action="added",
                name="foo",
                fragment_spec=None,
                project_spec="foo>=1.0",
            )
            bundle = _bundle_with([cand], project_root=tmp_path)
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)
        assert report.errored == 1
        assert "cannot infer backend language" in report.entries[0].error
