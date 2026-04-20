"""Golden-snapshot tests for generator output (4.5 of the 1.0 roadmap).

Each preset renders into a tempdir and its structure is compared against
a committed snapshot under ``tests/golden/snapshots/<preset>/``. Tests
capture *shape* (file list + sizes), not byte-exact content — byte
comparisons would fail on every innocuous template edit. When the shape
changes legitimately, update the snapshot by re-running with
``UPDATE_GOLDEN=1``.

The snapshot format is one JSON file per preset listing:
    {
      "files": {
        "relative/posix/path": {"size": 1234, "sha256": "abc..."},
        ...
      }
    }

Byte-level invariance is validated by the sha256. Legitimate template
edits regenerate the snapshot; regressions surface as test failures with
a diff between the expected and actual file maps.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate


SNAPSHOT_ROOT = Path(__file__).resolve().parent / "golden" / "snapshots"


def _snapshot_for(tmp_path: Path, project_root: Path) -> dict:
    """Capture the shape of every file under ``project_root``."""
    files: dict[str, dict] = {}
    for p in sorted(project_root.rglob("*")):
        if not p.is_file():
            continue
        # Skip volatile / user-agnostic paths.
        rel = p.relative_to(project_root).as_posix()
        if rel.startswith(".git/"):
            continue
        data = p.read_bytes().replace(b"\r\n", b"\n")
        files[rel] = {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()[:16],
        }
    return {"files": files}


def _compare(actual: dict, expected: dict) -> list[str]:
    """Return a list of human-readable differences between two snapshots."""
    diffs: list[str] = []
    actual_files = set(actual["files"])
    expected_files = set(expected["files"])

    added = actual_files - expected_files
    removed = expected_files - actual_files

    for p in sorted(added):
        diffs.append(f"+ added: {p} (size={actual['files'][p]['size']})")
    for p in sorted(removed):
        diffs.append(f"- removed: {p}")

    common = actual_files & expected_files
    for p in sorted(common):
        if actual["files"][p]["sha256"] != expected["files"][p]["sha256"]:
            diffs.append(
                f"~ content changed: {p} "
                f"(was {expected['files'][p]['sha256']}, now {actual['files'][p]['sha256']})"
            )
    return diffs


PRESETS = {
    "python_minimal": ProjectConfig(
        project_name="snap_py",
        backends=[
            BackendConfig(
                name="api",
                project_name="snap_py",
                language=BackendLanguage.PYTHON,
                features=["items"],
            )
        ],
        frontend=None,
    ),
}


@pytest.mark.parametrize("preset_name", list(PRESETS))
def test_golden_snapshot(preset_name: str, tmp_path: Path) -> None:
    """Render the preset into a tempdir; compare its shape to the snapshot.

    Set ``UPDATE_GOLDEN=1`` to regenerate the snapshot file (use sparingly —
    snapshots are the regression-detection layer).
    """
    config = PRESETS[preset_name]
    # Rewrite output_dir to the tempdir so we don't pollute the repo.
    config_copy = ProjectConfig(
        project_name=config.project_name,
        output_dir=str(tmp_path),
        backends=list(config.backends),
        frontend=config.frontend,
    )

    project_root = generate(config_copy, quiet=True, dry_run=True)
    actual = _snapshot_for(tmp_path, project_root)

    snapshot_file = SNAPSHOT_ROOT / f"{preset_name}.json"
    if os.getenv("UPDATE_GOLDEN") == "1" or not snapshot_file.is_file():
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        snapshot_file.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        pytest.skip(f"Regenerated snapshot: {snapshot_file}")

    expected = json.loads(snapshot_file.read_text(encoding="utf-8"))
    diffs = _compare(actual, expected)
    assert not diffs, (
        f"Golden snapshot drift for {preset_name}:\n"
        + "\n".join(diffs)
        + "\n\n"
        + "If these changes are intentional, re-run with UPDATE_GOLDEN=1."
    )
