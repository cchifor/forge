"""Tests for ``apply_bundle_to_fragments`` structural-files dispatch.

This module covers the structural branch of ``_apply_files_candidate``
(``risk == "conflict"``) — both the user and the upstream fragment moved
divergently from the recorded baseline, so a wholesale replace would
clobber the upstream change. The structural handler writes the user's
text into the fragment tree AND emits a ``<target>.forge-merge`` sidecar
carrying the upstream-emitted body for manual reconciliation.

The literal-files branch (``risk == "safe-apply"``) is covered by the
mixed-kind integration tests in ``tests/test_apply_bundle_deps_env.py``;
this module focuses on the conflict path that landed in Theme 3A.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.extractors.pipeline import CandidatePatch
from forge.fragments import FRAGMENT_REGISTRY, Fragment, FragmentImplSpec
from forge.sync.project_to_forge.apply_bundle import (
    _is_structural_files_candidate,
    apply_bundle_to_fragments,
)
from forge.sync.project_to_forge.harvester import HarvestBundle


# ---------------------------------------------------------------------------
# Scaffolding helpers — mirror the conventions in
# tests/test_apply_bundle_deps_env.py so the structural-files tests can
# stand alone without dragging that module's helpers in via import.
# ---------------------------------------------------------------------------


def _register_synthetic_fragment(
    name: str,
    *,
    fragment_dir: str = "_synthetic_structural",
) -> Fragment:
    """Register a synthetic fragment so apply-back's registry-lookup hits."""
    impls = {
        BackendLanguage.PYTHON: FragmentImplSpec(
            fragment_dir=fragment_dir,
            dependencies=(),
            env_vars=(),
        )
    }
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


def _make_forge_repo_with_fragment_file(
    forge_repo: Path,
    *,
    fragment_dir_str: str,
    rel_path: str,
    upstream_body: str,
) -> Path:
    """Lay out a synthetic forge_repo with the fragment-shipped upstream file.

    Returns the absolute path of the on-disk fragment file (i.e. the
    ``target`` the apply-back would write).
    """
    fragment_files_dir = (
        forge_repo / "forge" / "templates" / "_fragments" / fragment_dir_str / "files"
    )
    fragment_files_dir.mkdir(parents=True, exist_ok=True)
    target = fragment_files_dir / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(upstream_body, encoding="utf-8")
    return target


def _bundle_with(cands: list[CandidatePatch], *, project_root: Path) -> HarvestBundle:
    return HarvestBundle(
        bundle_id="harvest-structural-test",
        project_root=project_root,
        forge_version="0.0.0-test",
        candidates=cands,
    )


# ---------------------------------------------------------------------------
# Predicate
# ---------------------------------------------------------------------------


class TestIsStructuralFilesCandidate:
    """The predicate that drives the literal-vs-structural split."""

    def _cand(self, risk: str, kind: str = "files") -> CandidatePatch:
        return CandidatePatch(
            fragment="dummy",
            backend="api",
            kind=kind,
            rel_path="foo.py",
            target_path="/tmp/foo.py",
            diff="",
            baseline_sha="0" * 64,
            current_sha="1" * 64,
            risk=risk,
        )

    def test_safe_apply_is_literal(self) -> None:
        assert _is_structural_files_candidate(self._cand("safe-apply")) is False

    def test_needs_review_is_literal(self) -> None:
        assert _is_structural_files_candidate(self._cand("needs-review")) is False

    def test_conflict_is_structural(self) -> None:
        assert _is_structural_files_candidate(self._cand("conflict")) is True


# ---------------------------------------------------------------------------
# Apply-bundle: structural files candidate end-to-end
# ---------------------------------------------------------------------------


class TestApplyBundleFilesStructural:
    def test_conflict_writes_user_text_and_emits_sidecar(self, tmp_path: Path) -> None:
        """Conflict-risk files candidate: user's text lands in the fragment
        tree AND a ``.forge-merge`` sidecar carries the upstream body so
        the maintainer can reconcile the diverging trajectories."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_files_structural_conflict"
        fragment_dir_str = "_synthetic_structural_conflict"
        rel_path = "lib/middleware.py"
        upstream_body = (
            "# upstream-moved version: forge added a request id middleware.\n"
            "def middleware(request):\n"
            "    request.id = generate_id()\n"
            "    return request\n"
        )
        target = _make_forge_repo_with_fragment_file(
            forge_repo,
            fragment_dir_str=fragment_dir_str,
            rel_path=rel_path,
            upstream_body=upstream_body,
        )

        # User's project-side file — diverged from upstream + baseline.
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_file = project_dir / rel_path
        project_file.parent.mkdir(parents=True, exist_ok=True)
        user_body = (
            "# user-edited version: added logging, no request id work.\n"
            "def middleware(request):\n"
            "    log.info('request: %s', request)\n"
            "    return request\n"
        )
        project_file.write_text(user_body, encoding="utf-8")

        _register_synthetic_fragment(fragment_name, fragment_dir=fragment_dir_str)
        try:
            cand = CandidatePatch(
                fragment=fragment_name,
                backend="api",
                kind="files",
                rel_path=rel_path,
                target_path=str(project_file),
                diff="<unified diff omitted for test>",
                baseline_sha="0" * 64,
                current_sha="1" * 64,
                risk="conflict",
                rationale="user and upstream both diverged from baseline",
                current_body=user_body,
            )
            bundle = _bundle_with([cand], project_root=project_dir)
            # ``conflict`` isn't in the default risk filter; explicitly
            # opt in for the structural path.
            report = apply_bundle_to_fragments(
                bundle,
                forge_repo,
                risk_filter=("safe-apply", "conflict"),
                quiet=True,
            )
        finally:
            _unregister_fragment(fragment_name)

        # Exactly one applied entry, no errors.
        assert report.applied == 1, [(e.status, e.error) for e in report.entries]
        assert report.errored == 0
        entry = report.entries[0]
        assert entry.status == "applied"
        # The error field carries the sidecar path so reviewers see the conflict.
        assert "sidecar" in entry.error
        # The fragment file now carries the user's text (the user's edits land).
        assert target.read_text(encoding="utf-8") == user_body
        # A sidecar exists carrying the upstream body so the maintainer
        # can manually merge.
        sidecar = target.with_suffix(target.suffix + ".forge-merge")
        assert sidecar.is_file()
        sidecar_content = sidecar.read_text(encoding="utf-8")
        # The sidecar's body section contains the upstream body verbatim.
        assert upstream_body in sidecar_content
        # The sidecar header tags the conflict source so consumers can grep.
        assert "tag:" in sidecar_content
        assert fragment_name in sidecar_content

    def test_safe_apply_does_not_emit_sidecar(self, tmp_path: Path) -> None:
        """Safe-apply files candidate takes the LITERAL path — wholesale
        replace, no sidecar. This is the regression guard: a future change
        to the dispatcher that mis-routes safe-apply through the structural
        handler would silently pollute every literal apply with a sidecar."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_files_safe_apply_no_sidecar"
        fragment_dir_str = "_synthetic_safe_apply"
        rel_path = "lib/util.py"
        upstream_body = "def util():\n    pass\n"
        target = _make_forge_repo_with_fragment_file(
            forge_repo,
            fragment_dir_str=fragment_dir_str,
            rel_path=rel_path,
            upstream_body=upstream_body,
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_file = project_dir / rel_path
        project_file.parent.mkdir(parents=True, exist_ok=True)
        user_body = "def util():\n    return 1  # user edit\n"
        project_file.write_text(user_body, encoding="utf-8")

        _register_synthetic_fragment(fragment_name, fragment_dir=fragment_dir_str)
        try:
            cand = CandidatePatch(
                fragment=fragment_name,
                backend="api",
                kind="files",
                rel_path=rel_path,
                target_path=str(project_file),
                diff="",
                baseline_sha=None,
                current_sha="",
                risk="safe-apply",
                current_body=user_body,
            )
            bundle = _bundle_with([cand], project_root=project_dir)
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.applied == 1
        assert report.entries[0].error == ""  # no sidecar reference
        # Target carries user content.
        assert target.read_text(encoding="utf-8") == user_body
        # NO sidecar emitted on the literal path.
        sidecar = target.with_suffix(target.suffix + ".forge-merge")
        assert not sidecar.exists()

    def test_conflict_missing_source_file_is_errored(self, tmp_path: Path) -> None:
        """If the source file disappears between harvest and apply, the
        structural path surfaces ``errored`` — same contract as the
        literal path. The bundle is stale; the operator needs to know."""
        forge_repo = tmp_path / "forge-clone"
        fragment_name = "test_files_structural_missing"
        fragment_dir_str = "_synthetic_missing"
        rel_path = "lib/gone.py"
        _make_forge_repo_with_fragment_file(
            forge_repo,
            fragment_dir_str=fragment_dir_str,
            rel_path=rel_path,
            upstream_body="upstream\n",
        )

        # Construct a candidate pointing at a file that doesn't exist.
        missing_source = tmp_path / "does-not-exist.py"

        _register_synthetic_fragment(fragment_name, fragment_dir=fragment_dir_str)
        try:
            cand = CandidatePatch(
                fragment=fragment_name,
                backend="api",
                kind="files",
                rel_path=rel_path,
                target_path=str(missing_source),
                diff="",
                baseline_sha="0" * 64,
                current_sha="1" * 64,
                risk="conflict",
            )
            bundle = _bundle_with([cand], project_root=tmp_path)
            report = apply_bundle_to_fragments(
                bundle,
                forge_repo,
                risk_filter=("safe-apply", "conflict"),
                quiet=True,
            )
        finally:
            _unregister_fragment(fragment_name)

        assert report.errored == 1
        entry = report.entries[0]
        assert entry.status == "errored"
        assert "source file gone" in entry.error

    def test_conflict_unregistered_fragment_is_errored(self, tmp_path: Path) -> None:
        """A conflict candidate whose fragment isn't in the registry
        surfaces ``errored`` — same shape as the literal path. Plugins
        being disabled between harvest + apply is the canonical case."""
        forge_repo = tmp_path / "forge-clone"
        project_file = tmp_path / "x.py"
        project_file.write_text("user\n", encoding="utf-8")

        cand = CandidatePatch(
            fragment="not_registered_anywhere",
            backend="api",
            kind="files",
            rel_path="x.py",
            target_path=str(project_file),
            diff="",
            baseline_sha="0" * 64,
            current_sha="1" * 64,
            risk="conflict",
        )
        bundle = _bundle_with([cand], project_root=tmp_path)
        report = apply_bundle_to_fragments(
            bundle,
            forge_repo,
            risk_filter=("safe-apply", "conflict"),
            quiet=True,
        )

        assert report.errored == 1
        assert "not in registry" in report.entries[0].error
