"""Regression: plan_update predicts the RENDERED path of .jinja fragment
files, not a phantom .jinja path (audit #11).

The real applier (`appliers/files.py::copy_files`) renders `*.jinja` sources
and writes them with the suffix stripped (`_service.py.jinja` ->
`_service.py`), hashing the rendered body, and skips ephemeral build
artefacts (`__pycache__`, caches). `plan_update`'s preview walked the fragment
`files/` tree with no jinja/ephemeral awareness: it kept the `.jinja` suffix,
computed a destination that never exists on disk, and reported `action="new"`
for a phantom `*.jinja` path — while the real rendered file's
conflict/applied/skipped decision was never produced (so the preview was wrong
about exactly the files a fragment ships templated).

The connectors_registry fragment ships `_service.py.jinja` (rendered to
`_service.py`), so a connectors-enabled project exercises the bug.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendConfig, ProjectConfig
from forge.generator import generate
from forge.sync.forge_to_project.plan import plan_update


def _connectors_project(tmp_path: Path) -> Path:
    cfg = ProjectConfig(
        project_name="planj",
        output_dir=str(tmp_path),
        backends=[BackendConfig(name="api", project_name="planj", server_port=5000)],
        options={"connectors.enabled": True},
    )
    return generate(cfg, quiet=True, dry_run=True)


def test_plan_update_decides_rendered_jinja_paths(tmp_path: Path) -> None:
    root = _connectors_project(tmp_path)
    report = plan_update(root)
    rels = [e.rel_path for e in report.file_decisions]

    # No phantom raw-template path (a `*.jinja` dst that never exists on disk).
    phantom = [r for r in rels if r.endswith(".jinja")]
    assert not phantom, f"plan_update emitted phantom .jinja entries: {phantom}"

    # The rendered (suffix-stripped) connectors service file must be decided.
    svc = [e for e in report.file_decisions if e.rel_path.endswith("connectors/_service.py")]
    assert svc, (
        "plan_update never decided the rendered connectors/_service.py — it only saw the "
        "raw _service.py.jinja template path"
    )

    # No ephemeral build artefacts (e.g. __pycache__/*.pyc) leak into the plan.
    ephemeral = [r for r in rels if "__pycache__" in r or r.endswith(".pyc")]
    assert not ephemeral, f"plan_update emitted ephemeral artefacts: {ephemeral}"
