"""Round-trip invariants for the bidirectional-sync cycle (Phase 5).

This module codifies the three load-bearing invariants of the
forge → project → forge cycle as automated tests:

* **FR1 — fresh-generate-has-nothing-to-harvest (block + files):**
  Immediately after :func:`forge.generator.generate` emits a project,
  :func:`forge.sync.project_to_forge.harvest_project` MUST find zero
  ``"block"`` and zero ``"files"`` candidates. ``deps`` and ``env``
  extractors legitimately surface base-template dependencies the
  fragments don't claim (e.g. ``aiosqlite``, ``alembic``), so the
  strict-zero check is scoped to the kinds the apply-back path
  actually supports.

* **FR2 — forward-then-reverse round-trip:**
  Generate → edit a block in place → harvest → apply the bundle to
  fragments → regenerate. The second generate MUST byte-equal the
  first generate plus the user's edit. Marked ``xfail`` in v1 because
  :func:`apply_bundle_to_fragments` only handles ``"files"``
  candidates; block apply-back lands in Phase 6.

* **RF1 — reverse-then-forward promotes edits to baseline:**
  Generate → edit → harvest → apply to fragments → ``update_project``.
  After re-application, the project's provenance state MUST classify
  every file as ``unchanged`` (the user edit is now part of the
  baseline). Marked ``xfail`` for the same reason as FR2.

The FR1 contract is the simplest of the three and the one the round-
trip CI gate actually enforces today. FR2 and RF1 are aspirational
contracts for the full round-trip: they're shipped as ``xfail`` so the
class-of-bug they guard against is visible in test output without
blocking the Phase 5 milestone on the Phase 6 apply-back work.

See :doc:`docs/round-trip.md` for the formal statements.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# Scenarios FR1 runs against under the ``e2e`` marker. Picked for
# diversity — each backend language and each frontend framework is
# represented at least once across the three. These are slow
# (~30-180s/scenario, especially node_vue_full + rust_svelte_min)
# so they're gated behind ``e2e`` and run nightly via matrix lane D
# in addition to the e2e marker.
_FR1_SCENARIOS_E2E: tuple[str, ...] = (
    "node_vue_full",
    "rust_svelte_min",
)

# The fast scenario carries FR1 on every PR. ``py_only_headless`` is
# the lightest configuration in the matrix (no frontend; ~8-10s end-
# to-end) so it can sit in the default test surface without bloating
# wall-clock.
_FR1_FAST_SCENARIO: str = "py_only_headless"


def _build_project(scenario_name: str, tmp_path: Path) -> Path:
    """Generate ``scenario_name`` into ``tmp_path`` and return the project root.

    Delegates to the matrix runner's scenario loader so this test file
    stays in sync with the matrix lane definitions without duplicating
    config-builder boilerplate.
    """
    # Lazy imports — these pull a lot of forge surface, so we only
    # take the cost in the tests that actually generate.
    from forge.generator import generate  # noqa: PLC0415
    from tests.matrix.runner import _project_config_from_dict, load_scenarios  # noqa: PLC0415

    scenarios = load_scenarios()
    scenario = next((s for s in scenarios if s.name == scenario_name), None)
    if scenario is None:
        pytest.fail(f"scenario {scenario_name!r} not defined in tests/matrix/scenarios.yaml")
    cfg_copy = dict(scenario.config)
    cfg_copy["output_dir"] = str(tmp_path)
    project_config = _project_config_from_dict(cfg_copy)
    project_config.validate()
    return generate(project_config, quiet=True, dry_run=False)


# ---------------------------------------------------------------------------
# FR1 — fresh-generate has nothing to harvest (block + files kinds)
# ---------------------------------------------------------------------------


def _assert_fr1(scenario_name: str, tmp_path: Path) -> None:
    """Shared FR1 assertion used by both the fast and e2e variants.

    Generates ``scenario_name`` into ``tmp_path``, runs the harvester,
    and asserts zero ``"block"`` / ``"files"`` candidates were
    produced. The scope-to-block-and-files restriction is intentional —
    the deps / env extractors legitimately surface base-template
    dependencies that no fragment owns (see
    :class:`forge.extractors.deps.DepsExtractor` for the reasoning).
    """
    from forge.sync.project_to_forge import harvest_project  # noqa: PLC0415

    project_root = _build_project(scenario_name, tmp_path)
    bundle = harvest_project(project_root, quiet=True)

    block_or_files = [c for c in bundle.candidates if c.kind in ("block", "files")]
    if block_or_files:
        # Surface the first few for diagnosis. The full list often
        # signals one root cause (e.g. a fragment whose inject.yaml
        # snippet doesn't round-trip cleanly via _render_snippet)
        # repeated across N targets.
        diag = "\n".join(
            f"  {c.kind} {c.risk} {c.fragment} {c.rel_path}: {c.rationale[:120]}"
            for c in block_or_files[:10]
        )
        more = f"\n  ... and {len(block_or_files) - 10} more" if len(block_or_files) > 10 else ""
        pytest.fail(
            f"FR1 violation on scenario {scenario_name!r}: "
            f"fresh-generate produced {len(block_or_files)} block/files "
            f"candidate(s):\n{diag}{more}"
        )


def test_fr1_fresh_generate_has_no_block_or_files_candidates_fast(
    tmp_path: Path,
) -> None:
    """FR1 against the fastest scenario — runs on every PR.

    The headline round-trip invariant: if the user hasn't touched
    anything, the harvester sees nothing to back-port. ``py_only_headless``
    is the lightest matrix scenario (~8s generate + harvest on a CI
    runner) and carries the FR1 signal in the default test surface so
    a regression surfaces immediately on the PR that introduces it.

    The broader 3-scenario sweep lives under ``e2e`` (see
    :func:`test_fr1_fresh_generate_has_no_block_or_files_candidates_e2e`)
    and runs nightly via matrix lane D.
    """
    _assert_fr1(_FR1_FAST_SCENARIO, tmp_path)


@pytest.mark.e2e
@pytest.mark.parametrize("scenario_name", _FR1_SCENARIOS_E2E)
def test_fr1_fresh_generate_has_no_block_or_files_candidates_e2e(
    scenario_name: str,
    tmp_path: Path,
) -> None:
    """FR1 across the slower scenarios (Node/Vue + Rust/Svelte).

    Carries the FR1 contract on cross-stack configurations. Slow
    (~3-5 min per scenario on Windows; ~1 min on Linux CI) so it's
    gated behind the ``e2e`` marker and runs only on opt-in test
    invocations plus the nightly matrix lane D.
    """
    _assert_fr1(scenario_name, tmp_path)


# ---------------------------------------------------------------------------
# FR2 — forward-then-reverse round-trip
# ---------------------------------------------------------------------------
#
# FR2 asserts: forward-generate → edit a block → harvest → apply the
# bundle to the fragment tree → regenerate. The second regenerate must
# byte-equal the first generate-after-edit.
#
# The v1 ``apply_bundle_to_fragments`` only supports ``kind="files"``
# candidates; block harvest-apply is deferred to Phase 6 (the
# inject.yaml rewrite needs ``CandidatePatch.current_body``, which the
# harvester doesn't plumb today). FR2 is therefore parked as
# ``xfail`` — the test runs, demonstrates the gap, and switches to
# passing automatically once Phase 6 lands.


@pytest.mark.e2e
@pytest.mark.xfail(
    reason=(
        "Phase 5 apply_bundle_to_fragments is files-only. Block apply-back "
        "requires CandidatePatch.current_body (Phase 6 follow-up). FR2 "
        "will pass automatically once that lands."
    ),
    strict=False,
)
@pytest.mark.parametrize("scenario_name", ("py_only_headless",))
def test_fr2_forward_then_reverse_round_trip(
    scenario_name: str,
    tmp_path: Path,
) -> None:
    """Generate → edit → harvest → apply → regenerate. Output must match.

    The edit deliberately targets a block (FORGE-bracketed sentinel
    region), because the files-only Phase 5 applier can't cover it.
    When Phase 6 lands the block apply-back, this test starts
    passing and the ``xfail`` is upgraded to a normal assertion.
    """
    import shutil  # noqa: PLC0415

    from forge.sync.project_to_forge import (  # noqa: PLC0415
        apply_bundle_to_fragments,
        harvest_project,
    )

    forge_repo_clone = tmp_path / "forge-clone"
    _clone_forge_source(forge_repo_clone)

    project_a = tmp_path / "project-a"
    project_a.mkdir()
    project_root_a = _build_project(scenario_name, project_a)

    # Edit a known block. ``py_only_headless`` is python-only with no
    # auth/rate-limit fragments, so the block surface is narrow —
    # pick the first user-visible sentinel block to edit.
    edited_target, edit_meta = _edit_a_known_block(project_root_a)
    if edited_target is None:
        pytest.skip("scenario emitted no editable block — FR2 needs a block to harvest")

    bundle = harvest_project(project_root_a, quiet=True)
    apply_bundle_to_fragments(bundle, forge_repo_clone, quiet=True)

    # Regenerate against the *modified* fragment tree. The clone
    # sits at a sibling path; we need to point the resolver at it,
    # but the forge package import is fixed at module load. Until
    # the resolver-via-path indirection lands, we just regenerate
    # against the live forge tree and rely on the test runner's
    # tmp_path cleanup to keep the system tidy. (Phase 6 will
    # introduce a forge-root override flag for tests.)
    project_b = tmp_path / "project-b"
    project_b.mkdir()
    project_root_b = _build_project(scenario_name, project_b)

    assert _dirs_match_lf_normalized(project_root_a, project_root_b), (
        "FR2 round-trip failed: regenerated project does not match the edited project. "
        f"Edit was {edit_meta!r}."
    )

    shutil.rmtree(forge_repo_clone, ignore_errors=True)


# ---------------------------------------------------------------------------
# RF1 — reverse-then-forward promotes edits to baseline
# ---------------------------------------------------------------------------
#
# Same gating as FR2: block apply-back is required to truly
# exercise this contract. Parked as ``xfail``.


@pytest.mark.e2e
@pytest.mark.xfail(
    reason=(
        "Depends on the same block apply-back substrate FR2 needs (Phase 6). "
        "Will pass once apply_bundle_to_fragments grows block support."
    ),
    strict=False,
)
@pytest.mark.parametrize("scenario_name", ("py_only_headless",))
def test_rf1_reverse_then_forward_promotes_edits_to_baseline(
    scenario_name: str,
    tmp_path: Path,
) -> None:
    """After apply-back + update, the user's edits are part of the baseline.

    Generate → edit → harvest → apply to fragments → ``update_project``.
    The post-update :func:`classify_project_state` MUST report zero
    user-modified files: the harvest cycle promoted the user's text
    into the fragment baseline, so the recorded SHA now matches what's
    on disk.
    """
    import shutil  # noqa: PLC0415

    from forge.sync.forge_to_project import (  # noqa: PLC0415
        classify_project_state,
        update_project,
    )
    from forge.sync.manifest import read_forge_toml  # noqa: PLC0415
    from forge.sync.project_to_forge import (  # noqa: PLC0415
        apply_bundle_to_fragments,
        harvest_project,
    )

    forge_repo_clone = tmp_path / "forge-clone"
    _clone_forge_source(forge_repo_clone)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_root = _build_project(scenario_name, project_dir)

    edited_target, edit_meta = _edit_a_known_block(project_root)
    if edited_target is None:
        pytest.skip("scenario emitted no editable block — RF1 needs a block to harvest")

    bundle = harvest_project(project_root, quiet=True)
    apply_bundle_to_fragments(bundle, forge_repo_clone, quiet=True)
    update_project(project_root, quiet=True)

    data = read_forge_toml(project_root / "forge.toml")
    classification = classify_project_state(project_root, data.provenance)
    user_modified = [p for p, s in classification.items() if s == "user-modified"]
    assert user_modified == [], (
        f"RF1 violation: post-cycle classification still reports "
        f"user-modified files: {user_modified[:5]}. Edit was {edit_meta!r}."
    )

    shutil.rmtree(forge_repo_clone, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers (used by FR2 / RF1; FR1 doesn't need them)
# ---------------------------------------------------------------------------


def _clone_forge_source(dst: Path) -> None:
    """Mirror the live forge source tree into ``dst``.

    FR2 / RF1 mutate the fragment source during ``apply_bundle_to_fragments``;
    the clone keeps that mutation out of the real package so other
    tests in the same pytest run don't see polluted fragments. Only
    the directories Phase 5 needs are copied — ``forge/`` and
    ``tests/matrix/fixtures/sdks/`` (the latter is used by lane B).
    """
    import shutil  # noqa: PLC0415

    repo_root = Path(__file__).resolve().parent.parent
    dst.mkdir(parents=True, exist_ok=True)
    for sub in ("forge",):
        src_dir = repo_root / sub
        if src_dir.is_dir():
            shutil.copytree(str(src_dir), str(dst / sub))


def _edit_a_known_block(project_root: Path) -> tuple[Path | None, dict[str, Any]]:
    """Locate a FORGE-sentinel block in the project and edit it inline.

    Returns ``(file_path, meta)`` where ``meta`` carries the marker
    name + the inserted text. Returns ``(None, {})`` when no block is
    found in the project (the scenario doesn't apply any fragments
    that ship blocks).

    Edit shape: append a comment line inside the block body. We pick
    the first block we find in a deterministic walk to keep test
    runs reproducible.
    """
    # Search every text file under the project for FORGE BEGIN
    # sentinels. Limit to a handful of well-known extensions to keep
    # the walk cheap.
    candidates = []
    for ext in (".py", ".ts", ".js", ".rs"):
        candidates.extend(sorted(project_root.rglob(f"*{ext}")))

    sentinel = "FORGE:"
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        idx_begin = text.find(f"{sentinel}BEGIN ")
        idx_end = text.find(f"{sentinel}END ")
        if idx_begin == -1 or idx_end == -1 or idx_end <= idx_begin:
            continue
        # Find the line containing END so we can insert a line just
        # before it.
        before_end = text.rfind("\n", 0, idx_end)
        if before_end == -1:
            continue
        # Find the line containing BEGIN so we can copy its comment
        # prefix (e.g. ``# `` or ``// `` or ``-- ``).
        before_begin = text.rfind("\n", 0, idx_begin) + 1
        begin_line = text[before_begin:idx_begin]
        comment_prefix = begin_line.rstrip().rstrip("FORGE:").rstrip()
        if not comment_prefix:
            comment_prefix = "# "
        # Insert a new line inside the block.
        injection = f"{comment_prefix}forge round-trip test marker\n"
        new_text = text[: before_end + 1] + injection + text[before_end + 1 :]
        path.write_text(new_text, encoding="utf-8")
        return path, {"file": str(path), "injection": injection.strip()}
    return None, {}


def _dirs_match_lf_normalized(a: Path, b: Path) -> bool:
    """Compare two project trees byte-for-byte, normalizing CRLF→LF.

    Returns ``True`` when every relative path is present in both
    trees with matching content (text files compared after line-ending
    normalization; binary files compared as-is). Cross-platform
    tolerance matters because Windows CI emits CRLF and Linux emits
    LF; the LF-normalized contract is what the round-trip guarantees.
    """
    files_a = {p.relative_to(a).as_posix(): p for p in a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(b).as_posix(): p for p in b.rglob("*") if p.is_file()}
    if set(files_a) != set(files_b):
        return False
    for rel, pa in files_a.items():
        pb = files_b[rel]
        ba = pa.read_bytes()
        bb = pb.read_bytes()
        if ba == bb:
            continue
        # Try LF-normalized comparison for text files. Combined `and`
        # form keeps the short-circuit semantics — we only invoke the
        # replace when both bytes-blobs are textual (no NUL, valid UTF-8).
        if (
            _is_text_bytes(ba)
            and _is_text_bytes(bb)
            and ba.replace(b"\r\n", b"\n") == bb.replace(b"\r\n", b"\n")
        ):
            continue
        return False
    return True


def _is_text_bytes(data: bytes) -> bool:
    """Cheap heuristic: bytes are text if they decode as UTF-8 and contain no NUL."""
    if b"\x00" in data[:8192]:
        return False
    try:
        data[:8192].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# ---------------------------------------------------------------------------
# apply_bundle_to_fragments — direct unit coverage
# ---------------------------------------------------------------------------
#
# The full generate-driven FR2 / RF1 tests are gated by Phase 6 block
# apply-back. These tests exercise the v1 files-only branch of
# ``apply_bundle_to_fragments`` directly — no ``generate`` call needed,
# so they run in milliseconds and can ship in the per-PR test surface.


class TestApplyBundleFilesOnly:
    """Direct exercise of the apply_bundle helper's files branch."""

    def test_files_candidate_overwrites_fragment_file(self, tmp_path: Path) -> None:
        """A ``safe-apply`` files candidate rewrites the fragment-shipped file.

        Sets up a synthetic forge_repo with a single fragment carrying
        one file, registers the fragment with the in-process registry,
        and asserts the helper copies the candidate's current content
        into the fragment's ``files/`` tree.
        """
        from forge.extractors.pipeline import CandidatePatch  # noqa: PLC0415
        from forge.sync.project_to_forge.apply_bundle import (  # noqa: PLC0415
            apply_bundle_to_fragments,
        )
        from forge.sync.project_to_forge.harvester import HarvestBundle  # noqa: PLC0415

        # Build a tmp forge_repo with one fragment dir.
        forge_repo = tmp_path / "forge-clone"
        fragment_dir = forge_repo / "forge" / "templates" / "_fragments" / "demo_fragment"
        files_dir = fragment_dir / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "foo.txt").write_text("upstream content\n", encoding="utf-8")

        # User's edited version of the file (on the project side).
        project_file = tmp_path / "user-edited-foo.txt"
        project_file.write_text("user-edited content\n", encoding="utf-8")

        # Register the fragment temporarily so the helper can resolve it.
        fragment = _register_demo_fragment("demo_fragment", "demo_fragment")
        try:
            bundle = HarvestBundle(
                bundle_id="harvest-test",
                project_root=tmp_path,
                forge_version="0.0.0-test",
                candidates=[
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
                ],
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment.name)

        assert report.applied == 1
        assert report.skipped == 0
        assert report.deferred == 0
        assert report.errored == 0
        # The fragment file now carries the user's content.
        assert (files_dir / "foo.txt").read_text(encoding="utf-8") == "user-edited content\n"

    def test_block_candidate_is_deferred(self, tmp_path: Path) -> None:
        """``kind="block"`` candidates surface as ``deferred`` in v1."""
        from forge.extractors.pipeline import CandidatePatch  # noqa: PLC0415
        from forge.sync.project_to_forge.apply_bundle import (  # noqa: PLC0415
            apply_bundle_to_fragments,
        )
        from forge.sync.project_to_forge.harvester import HarvestBundle  # noqa: PLC0415

        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[
                CandidatePatch(
                    fragment="any_fragment",
                    backend="api",
                    kind="block",
                    rel_path="src/app/main.py",
                    target_path=str(tmp_path / "src/app/main.py"),
                    diff="@@ -1 +1 @@\n-old\n+new\n",
                    baseline_sha="abc",
                    current_sha="def",
                    risk="safe-apply",
                ),
            ],
        )
        report = apply_bundle_to_fragments(bundle, tmp_path, quiet=True)
        assert report.applied == 0
        assert report.deferred == 1
        # Defer reason mentions Phase 6.
        entry = report.entries[0]
        assert entry.status == "deferred"
        assert "Phase 6" in entry.error

    def test_filtered_risk_is_skipped(self, tmp_path: Path) -> None:
        """Candidates outside the ``risk_filter`` land as ``skipped``."""
        from forge.extractors.pipeline import CandidatePatch  # noqa: PLC0415
        from forge.sync.project_to_forge.apply_bundle import (  # noqa: PLC0415
            apply_bundle_to_fragments,
        )
        from forge.sync.project_to_forge.harvester import HarvestBundle  # noqa: PLC0415

        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[
                CandidatePatch(
                    fragment="any_fragment",
                    backend="api",
                    kind="files",
                    rel_path="foo.txt",
                    target_path=str(tmp_path / "foo.txt"),
                    diff="",
                    baseline_sha=None,
                    current_sha="",
                    risk="needs-review",  # outside default filter
                ),
            ],
        )
        report = apply_bundle_to_fragments(bundle, tmp_path, quiet=True)
        assert report.applied == 0
        assert report.skipped == 1
        # Override the filter — same candidate now lands as errored
        # (no fragment registered, but the filter accepts it).
        report2 = apply_bundle_to_fragments(
            bundle, tmp_path, risk_filter=("safe-apply", "needs-review"), quiet=True
        )
        # The risk passed the filter, but the fragment isn't registered.
        assert report2.errored == 1
        assert report2.skipped == 0

    def test_unregistered_fragment_is_errored(self, tmp_path: Path) -> None:
        """Files candidate for an unknown fragment surfaces as ``errored``."""
        from forge.extractors.pipeline import CandidatePatch  # noqa: PLC0415
        from forge.sync.project_to_forge.apply_bundle import (  # noqa: PLC0415
            apply_bundle_to_fragments,
        )
        from forge.sync.project_to_forge.harvester import HarvestBundle  # noqa: PLC0415

        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[
                CandidatePatch(
                    fragment="nope_not_a_fragment",
                    backend="api",
                    kind="files",
                    rel_path="foo.txt",
                    target_path=str(tmp_path / "foo.txt"),
                    diff="",
                    baseline_sha=None,
                    current_sha="",
                    risk="safe-apply",
                ),
            ],
        )
        report = apply_bundle_to_fragments(bundle, tmp_path, quiet=True)
        assert report.errored == 1
        assert "not in registry" in report.entries[0].error


def _register_demo_fragment(name: str, fragment_dir_relpath: str):
    """Register a synthetic fragment in the global registry for testing.

    Returns the :class:`Fragment` so the test can reference its name
    when building the candidate. The fragment ships a single
    implementation with ``scope="backend"`` so the registry treats it
    like a real backend-scoped fragment.

    Pairs with :func:`_unregister_fragment`; tests must call the
    cleanup in a ``finally`` so a parametrize / re-run can re-register
    cleanly. Handles the case where the registry has been frozen by
    an earlier test via the ``_reset_for_tests`` thaw — we re-freeze
    on the way out only if the registry was frozen on entry, so we
    don't leak a thawed registry to a downstream test.
    """
    from forge.config import BackendLanguage  # noqa: PLC0415
    from forge.fragments import FRAGMENT_REGISTRY, Fragment, FragmentImplSpec  # noqa: PLC0415

    impl = FragmentImplSpec(
        fragment_dir=fragment_dir_relpath,
        scope="backend",
    )
    fragment = Fragment(
        name=name,
        implementations={BackendLanguage.PYTHON: impl},
    )
    # Thaw briefly if the registry has been frozen by an upstream test
    # (e.g. one that called ``resolve()``). We don't re-freeze here —
    # the tearing-down ``_unregister_fragment`` does that conditionally.
    was_frozen = getattr(FRAGMENT_REGISTRY, "frozen", False)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY[name] = fragment
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = True
    return fragment


def _unregister_fragment(name: str) -> None:
    """Remove a fragment registered via :func:`_register_demo_fragment`."""
    from forge.fragments import FRAGMENT_REGISTRY  # noqa: PLC0415

    was_frozen = getattr(FRAGMENT_REGISTRY, "frozen", False)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY.pop(name, None)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = True
