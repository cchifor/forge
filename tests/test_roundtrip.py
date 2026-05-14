"""End-to-end round-trip test for the bidirectional-sync cycle (Phase 5/6).

This file covers the headline user-visible guarantee:

    generate(config) ─→ user edits ─→ harvest_project ─→
    apply_bundle_to_fragments ─→ generate(config)  ==  edited project

Run only when the ``e2e`` marker is selected:

    uv run pytest tests/test_roundtrip.py -m e2e

The single scenario is ``py_only_headless`` — the lightest of the
matrix scenarios (~30s per generate) — chosen to keep the e2e budget
manageable while still exercising one full forward+reverse+forward
cycle through real fragments.

Companion to :mod:`tests.test_harvest_invariants`, which decomposes
the cycle into FR1 / FR2 / RF1. This file is the user-facing
"smoke test" for the entire bidirectional sync surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def test_roundtrip_py_only_headless(tmp_path: Path) -> None:
    """End-to-end forward→reverse→forward cycle for py_only_headless.

    Detailed steps:

    1. Generate the scenario into ``tmp_path/project-a``.
    2. Edit a known literal (non-Jinja) FORGE-sentinel block inline —
       the harvester's bread-and-butter target.
    3. Harvest the edited project into a :class:`HarvestBundle`.
    4. Apply the bundle to the LIVE forge tree (snapshotted + reverted
       in ``finally`` so the mutation doesn't bleed into other tests).
       This is necessary because the generator's fragment registry is
       a module-level singleton; applying to a clone has no effect on
       the second ``generate()``.
    5. Regenerate the scenario into ``tmp_path/project-b``.
    6. Assert ``project-a`` and ``project-b`` match modulo documented
       noise: emitted_at timestamps, sentinel fingerprints, derived
       sha256 fields, .git/ + .copier-answers.yml. See
       :func:`tests.test_harvest_invariants._diff_project_trees`.
    """
    from forge.sync.project_to_forge import (  # noqa: PLC0415
        apply_bundle_to_fragments,
        harvest_project,
    )

    # Reuse the FR2 helpers so the end-to-end smoke and the invariant
    # decomposition share a single canonical edit-and-compare
    # implementation.
    from tests.test_harvest_invariants import (  # noqa: PLC0415
        _build_project,
        _diff_project_trees,
        _edit_a_known_literal_block,
        _live_forge_apply_back_guard,
        _live_forge_root,
    )

    project_a_root = tmp_path / "project-a"
    project_a_root.mkdir()
    project_a = _build_project("py_only_headless", project_a_root)

    edited_path, edit_meta = _edit_a_known_literal_block(project_a)
    if edited_path is None:
        pytest.skip(
            "py_only_headless emitted no FORGE-sentinel literal block; "
            "scenarios must ship at least one block to exercise round-trip"
        )

    bundle = harvest_project(project_a, quiet=True)
    bundle.candidates[:] = [c for c in bundle.candidates if c.kind == "block"]
    if not any(c.risk == "safe-apply" for c in bundle.candidates):
        pytest.skip("no safe-apply block candidates after edit")

    with _live_forge_apply_back_guard():
        report = apply_bundle_to_fragments(bundle, _live_forge_root(), quiet=True)
        assert report.errored == 0, f"apply-back errored on {report.errored} candidate(s)"

        project_b_root = tmp_path / "project-b"
        project_b_root.mkdir()
        project_b = _build_project("py_only_headless", project_b_root)

        differing = _diff_project_trees(project_a, project_b)
        assert differing == [], (
            f"Round-trip failure: project-a (edited) and project-b (regenerated) "
            f"differ on {len(differing)} file(s); first: {differing[:5]}. "
            f"Edit was {edit_meta!r}."
        )
