"""Tests for the registry-based candidate dispatch in apply_bundle.

Initiative #1 sub-task 3 replaced the if/elif kind ladder at
``forge/sync/project_to_forge/apply_bundle/_dispatch.py`` with a typed
``dict[CandidateKind, ApplyHandler]`` registry. These tests pin the
registry's coverage contract (every non-accept-owned kind has a
handler) and the unknown-kind error path the dispatch falls into for
candidates that legitimately have no apply-back implementation
(``new-file`` today; future plugin kinds before sub-task 4 lands their
registration mechanism).
"""

from __future__ import annotations

from pathlib import Path

from forge.extractors.pipeline import CANDIDATE_KINDS, CandidatePatch
from forge.sync.project_to_forge.apply_bundle._dispatch import (
    _build_apply_handlers,
)
from forge.sync.project_to_forge.apply_bundle import apply_bundle_to_fragments
from forge.sync.project_to_forge.harvester import HarvestBundle


# ``new-file`` is intentionally absent from the apply_bundle registry —
# that kind is owned by the accept-baseline path
# (forge.sync.project_to_forge.accept), not by apply_bundle. Routing a
# new-file candidate through apply_bundle is a contract bug worth
# surfacing in the report.
_ACCEPT_OWNED_KINDS: frozenset[str] = frozenset({"new-file"})


class TestApplyHandlerRegistryCoverage:
    def test_registry_covers_every_non_accept_owned_kind(self) -> None:
        handlers = _build_apply_handlers()
        registered = set(handlers.keys())
        expected = set(CANDIDATE_KINDS) - _ACCEPT_OWNED_KINDS
        missing = expected - registered
        extra = registered - expected
        assert not missing, (
            f"apply_bundle registry missing handlers for: {sorted(missing)}. "
            "Add an entry in _build_apply_handlers() or mark the kind as "
            "accept-owned in this test."
        )
        assert not extra, (
            f"apply_bundle registry has handlers for kinds that are not in "
            f"CANDIDATE_KINDS: {sorted(extra)}. The Literal alias and the "
            "registry have drifted."
        )

    def test_every_registered_handler_is_callable(self) -> None:
        handlers = _build_apply_handlers()
        for kind, handler in handlers.items():
            assert callable(handler), f"handler for kind={kind!r} is not callable"


class TestUnknownKindSurfacesAsErrored:
    """An agent that forwards an accept-owned (``new-file``) candidate to
    apply_bundle should get a structured ``errored`` entry, not a
    silent drop or a Python exception. Same fall-through covers any
    future kind that's documented but not yet wired."""

    def test_new_file_routed_through_apply_bundle_is_errored(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        forge_repo.mkdir()

        candidate = CandidatePatch(
            fragment="demo_fragment",
            backend="api",
            kind="new-file",
            rel_path="extras/added_by_user.txt",
            target_path=str(tmp_path / "added_by_user.txt"),
            diff="",
            baseline_sha=None,
            current_sha="",
            risk="safe-apply",
        )
        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[candidate],
        )

        report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)

        assert report.applied == 0
        assert report.errored == 1
        assert len(report.entries) == 1
        entry = report.entries[0]
        assert entry.status == "errored"
        assert entry.kind == "new-file"
        assert "unknown candidate kind" in (entry.error or "")
