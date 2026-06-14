"""A freshly generated project must pass `forge --verify` (no day-0 drift).

The deps/env appliers append to per-backend manifests (pyproject.toml /
package.json / Cargo.toml / .env.example) AFTER provenance stamps them, so a
virgin project used to report those files as drift and `forge --verify`
exited 10 — making the documented CI-gate verb unusable. generate() now
re-records the mutated manifests; this locks that in."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate
from forge.sync.project_to_forge.verify import verify_project


@pytest.mark.parametrize(
    "lang,opts",
    [
        (BackendLanguage.PYTHON, {"observability.tracing": True, "middleware.rate_limit": True}),
        (BackendLanguage.NODE, {"middleware.rate_limit": True}),
        (BackendLanguage.RUST, {"middleware.rate_limit": True}),
        # database.mode=none runs the DB stripper, which rewrites
        # tests/unit/test_config.py + test_lifecycle.py in place — both must be
        # re-recorded post-strip or a virgin stateless project fails verify.
        (BackendLanguage.PYTHON, {"database.mode": "none"}),
    ],
)
def test_fresh_generate_verify_is_clean(lang, opts, tmp_path):
    cfg = ProjectConfig(
        project_name="vfresh",
        output_dir=str(tmp_path),
        backends=[BackendConfig(name="api", project_name="vfresh", language=lang, features=["items"])],
        options=opts,
        option_origins={k: "user" for k in opts},
    )
    root = Path(generate(cfg, quiet=True))
    res = verify_project(root, scope="all", fail_on="drift")
    drifted = [r.rel_path for r in res.records if r.status == "user-modified"]
    assert res.worst == "clean", f"fresh-generate verify not clean; drift on {drifted[:8]}"


def test_manifests_recorded_after_appliers(tmp_path):
    # The specific files the appliers mutate must NOT drift.
    cfg = ProjectConfig(
        project_name="vman",
        output_dir=str(tmp_path),
        backends=[BackendConfig(name="api", project_name="vman", language=BackendLanguage.PYTHON, features=["items"])],
        options={"object_store.backend": "s3"},  # adds env vars + deps
        option_origins={"object_store.backend": "user"},
    )
    root = Path(generate(cfg, quiet=True))
    res = verify_project(root, scope="all", fail_on="drift")
    drifted = {r.rel_path.rsplit("/", 1)[-1] for r in res.records if r.status == "user-modified"}
    assert not (drifted & {"pyproject.toml", ".env.example"}), f"manifest drift: {drifted}"


def test_verify_drift_surfaces_rel_path(tmp_path):
    # The drift diagnostic only evaluates ``r.rel_path`` for user-modified
    # records, so a clean fresh-generate never exercises it — a typo'd
    # attribute (the original ``r.path``) hid behind the happy path and would
    # only ``AttributeError`` once a real day-0 regression appeared. Force the
    # drift branch so the diagnostic stays exercised.
    cfg = ProjectConfig(
        project_name="vdrift",
        output_dir=str(tmp_path),
        backends=[BackendConfig(name="api", project_name="vdrift", language=BackendLanguage.PYTHON, features=["items"])],
    )
    root = Path(generate(cfg, quiet=True))
    clean = verify_project(root, scope="all", fail_on="drift")
    assert clean.worst == "clean"
    victim = next(r for r in clean.records if r.rel_path.endswith(".py"))
    fpath = root / victim.rel_path
    fpath.write_text(fpath.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    res = verify_project(root, scope="all", fail_on="drift")
    drifted = [r.rel_path for r in res.records if r.status == "user-modified"]
    assert victim.rel_path in drifted, f"expected {victim.rel_path} in drift list {drifted[:8]}"
