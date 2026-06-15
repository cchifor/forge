"""The topology-aware Helm chart stays current on ``forge --update``.

The chart is a project-scope fragment, so it rides the same
apply_project_features -> three-way-merge -> provenance rail every other
fragment uses. These tests pin the keep-current guarantees: an idempotent
no-op update, re-render from current topology, and preservation of user edits.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate
from forge.sync.forge_to_project.updater import update_project


def _gen_k8s(port: int = 8000) -> Path:
    cfg = ProjectConfig(
        project_name="keepcurrent",
        backends=[BackendConfig(name="api", language=BackendLanguage.PYTHON, server_port=port)],
        options={"deploy.target": "kubernetes"},
    )
    return generate(cfg, quiet=True, dry_run=True)


def _values_path(root: Path) -> Path:
    return root / "deploy" / "helm" / "values.yaml"


def test_update_is_idempotent_for_the_chart() -> None:
    root = _gen_k8s()
    before = _values_path(root).read_text(encoding="utf-8")

    summary = update_project(root, quiet=True)

    after = _values_path(root).read_text(encoding="utf-8")
    assert before == after, "chart values.yaml should be byte-identical on a no-op update"
    assert summary["file_conflicts"] == 0
    assert "deploy_helm_chart" in summary["fragments_applied"]


def test_update_rerenders_chart_from_current_topology() -> None:
    """Deleting a chart file then updating re-emits it from the live topology —
    this is the mechanism that keeps the chart current as the project changes."""
    root = _gen_k8s(port=8000)
    original = _values_path(root).read_text(encoding="utf-8")
    _values_path(root).unlink()

    update_project(root, quiet=True)

    assert _values_path(root).is_file(), "update must re-render the deleted chart values.yaml"
    regenerated = yaml.safe_load(_values_path(root).read_text(encoding="utf-8"))
    assert regenerated["workloads"]["api"]["containerPort"] == 8000
    # Re-render is deterministic.
    assert _values_path(root).read_text(encoding="utf-8") == original


def test_update_preserves_user_edits_to_values() -> None:
    """A user edit to the forge-owned values.yaml is not silently clobbered:
    merge mode preserves it (or drops a .forge-merge sidecar on real conflict)."""
    root = _gen_k8s()
    vp = _values_path(root)
    edited = vp.read_text(encoding="utf-8").replace("replicaCount: 2", "replicaCount: 99", 1)
    assert "replicaCount: 99" in edited
    vp.write_text(edited, encoding="utf-8")

    update_project(root, quiet=True)

    after = vp.read_text(encoding="utf-8")
    sidecar = vp.with_suffix(vp.suffix + ".forge-merge")
    # Either the user's edit survives in place, or it's preserved via a sidecar —
    # never silently overwritten back to the forge default.
    assert "replicaCount: 99" in after or sidecar.exists()
