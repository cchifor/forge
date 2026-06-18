"""Regression: update summary ``file_conflicts`` counts only real, new merge
conflicts (audit #12).

``_count_file_sidecars`` rglob'd every ``*.forge-merge`` / ``*.forge-merge.bin``
file and reported the total as ``file_conflicts``. But two sidecar populations
are NOT conflicts:

* **presurface edit-trail sidecars** — ``_presurface_user_modified_sidecars``
  writes a ``.forge-merge`` for every user-modified base-template file even when
  Copier later merges it cleanly (a record, not a conflict);
* **stale sidecars** from prior runs — presurface refuses to clobber a
  pre-existing sidecar, so unresolved sidecars persist and get re-counted.

So ``file_conflicts`` could be >0 on a run that produced zero new conflicts.
The fix counts only sidecars created by THIS run, minus the presurfaced set.
"""

from __future__ import annotations

from pathlib import Path

from forge.sync.forge_to_project.updater import (
    _count_new_file_conflicts,
    _sidecar_paths,
)


def test_file_conflicts_excludes_stale_and_presurfaced_sidecars(tmp_path: Path) -> None:
    # A stale sidecar from a prior run (pre-existing).
    stale = tmp_path / "stale.py.forge-merge"
    stale.write_text("<<< stale", encoding="utf-8")
    pre_existing = _sidecar_paths(tmp_path)
    assert pre_existing == {stale}

    # This run: a presurface edit-trail sidecar (clean merge, NOT a conflict)
    # and a real merge conflict sidecar.
    presurfaced = tmp_path / "clean.py.forge-merge"
    presurfaced.write_text("edit-trail", encoding="utf-8")
    real_conflict = tmp_path / "conflict.py.forge-merge.bin"
    real_conflict.write_bytes(b"<<< conflict")

    # The raw glob over-counts: it sees all three.
    assert len(_sidecar_paths(tmp_path)) == 3

    # The fixed counter excludes the stale + presurfaced sidecars, leaving
    # only the one real new conflict.
    count = _count_new_file_conflicts(tmp_path, pre_existing, {presurfaced})
    assert count == 1, f"expected 1 real conflict, got {count}"
