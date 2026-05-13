"""End-to-end round-trip test for the bidirectional-sync cycle (Phase 5).

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


@pytest.mark.xfail(
    reason=(
        "Phase 5 ships apply_bundle_to_fragments as files-only; block "
        "apply-back lands in Phase 6. The full forward→reverse→forward "
        "cycle currently fails on block-edited scenarios because the "
        "bundle's block candidates land as ``deferred`` and the edit "
        "is lost on regenerate. The test runs and demonstrates the gap; "
        "remove this xfail once Phase 6 wires block harvest application."
    ),
    strict=False,
)
def test_roundtrip_py_only_headless(tmp_path: Path) -> None:
    """End-to-end forward→reverse→forward cycle for py_only_headless.

    Detailed steps:

    1. Generate the scenario into ``tmp_path/project-a``.
    2. Edit a known FORGE-sentinel block inline (the harvester's bread-
       and-butter target).
    3. Harvest the edited project into a :class:`HarvestBundle`.
    4. Apply the bundle to a tmp-path clone of the forge source tree.
       Block candidates emit ``deferred`` entries in v1 — this is the
       crux of the xfail.
    5. Regenerate the scenario into ``tmp_path/project-b``.
    6. Assert ``project-a`` and ``project-b`` match byte-for-byte
       (CRLF/LF normalized). Failure means the user's edit was lost
       on regenerate — the round-trip didn't close.
    """
    from forge.sync.project_to_forge import (  # noqa: PLC0415
        apply_bundle_to_fragments,
        harvest_project,
    )

    # Import the helpers from the invariants module so we share one
    # canonical edit-and-compare implementation across the test surface.
    from tests.test_harvest_invariants import (  # noqa: PLC0415
        _build_project,
        _clone_forge_source,
        _dirs_match_lf_normalized,
        _edit_a_known_block,
    )

    forge_repo_clone = tmp_path / "forge-clone"
    _clone_forge_source(forge_repo_clone)

    project_a_root = tmp_path / "project-a"
    project_a_root.mkdir()
    project_a = _build_project("py_only_headless", project_a_root)

    edited_path, edit_meta = _edit_a_known_block(project_a)
    if edited_path is None:
        pytest.skip(
            "py_only_headless emitted no FORGE-sentinel block; "
            "scenarios must ship at least one block to exercise round-trip"
        )

    bundle = harvest_project(project_a, quiet=True)
    apply_bundle_to_fragments(bundle, forge_repo_clone, quiet=True)

    project_b_root = tmp_path / "project-b"
    project_b_root.mkdir()
    project_b = _build_project("py_only_headless", project_b_root)

    assert _dirs_match_lf_normalized(project_a, project_b), (
        f"Round-trip failure: project-a (edited) and project-b (regenerated) "
        f"don't match. Edit was {edit_meta!r}."
    )
