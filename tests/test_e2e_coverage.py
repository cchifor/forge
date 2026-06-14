"""Guard: the full e2e suite must run somewhere unfiltered.

The PR-time e2e presets select tests by ``-k <preset>``, which covered only
~12 of ~59 e2e tests — the rest (standalone-build, layout-builds,
platform-compose-boot, tenant-isolation, the flagship suites of PRs #169/#170/
#193) were dark in every workflow, so regressions in them shipped unnoticed.
The fix is a nightly job that runs ``pytest -m e2e`` with NO ``-k`` filter.

This guard locks that in: if someone narrows the nightly job back down to a
``-k`` filter, or deletes it, this test fails. It mechanizes the WS-5.1 lesson
('a test that no workflow selects is a test that does not run')."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_E2E_YML = _REPO / ".github" / "workflows" / "e2e.yml"
_PLATFORM_BOOT_YML = _REPO / ".github" / "workflows" / "e2e-platform-boot.yml"
_PLATFORMS_ROOT = _REPO / "forge" / "templates" / "platforms"
_BOOT_TEST = _REPO / "tests" / "e2e" / "test_platform_compose_boot.py"


def _load_jobs() -> dict:
    return yaml.safe_load(_E2E_YML.read_text(encoding="utf-8"))["jobs"]


def test_unfiltered_nightly_job_exists():
    jobs = _load_jobs()
    assert "e2e-nightly-full" in jobs, (
        "the full-e2e nightly job is missing — without it ~80% of e2e tests run in no workflow"
    )


def test_nightly_job_runs_e2e_without_k_filter():
    job = _load_jobs()["e2e-nightly-full"]
    run_steps = [s.get("run", "") for s in job["steps"] if isinstance(s, dict) and "run" in s]
    e2e_runs = [r for r in run_steps if "pytest" in r and "-m e2e" in r]
    assert e2e_runs, "the nightly job must run `pytest -m e2e`"
    for r in e2e_runs:
        assert not re.search(r"-k\b", r), (
            "the nightly full-e2e run must NOT carry a -k filter — that is what "
            "darkened 47 of 59 e2e tests in the first place"
        )


def test_nightly_job_is_schedule_gated():
    # It's expensive (all toolchains + docker); keep it off the PR path.
    job = _load_jobs()["e2e-nightly-full"]
    assert "schedule" in str(job.get("if", "")), "nightly full-e2e should be schedule-gated"


def test_nightly_reports_skips():
    # Env-gated tests must surface as reported skips (-rs), not silent passes.
    job = _load_jobs()["e2e-nightly-full"]
    run = " ".join(s.get("run", "") for s in job["steps"] if isinstance(s, dict) and "run" in s)
    assert "-rs" in run, "use `pytest -rs` so env-gated e2e skips are visible"


# ── Platform preset boot coverage ───────────────────────────────────────────
# The nightly un-darks every e2e test, but a flagship *platform* regression
# needs a PR-time signal too — the multitenant-saas preset shipped red for three
# nights because its compose-boot test ran only nightly. These guards lock in
# (a) a PR-triggerable boot lane and (b) that every `--platform` preset has a
# compose-boot test, so a new preset can't ship with zero boot coverage.


def test_pr_platform_boot_lane_exists():
    assert _PLATFORM_BOOT_YML.is_file(), (
        "the PR-triggerable platform compose-boot lane (e2e-platform-boot.yml) is "
        "missing — platform regressions would only surface in the nightly"
    )
    wf = yaml.safe_load(_PLATFORM_BOOT_YML.read_text(encoding="utf-8"))
    # ``on`` parses to the bool True under YAML 1.1; index by that key.
    triggers = wf.get(True, wf.get("on", {}))
    paths = triggers.get("pull_request", {}).get("paths", [])
    assert any("platforms" in p for p in paths), (
        "platform-boot lane must fire on PRs touching forge/templates/platforms/**"
    )
    runs = " ".join(
        s.get("run", "")
        for job in wf["jobs"].values()
        for s in job.get("steps", [])
        if isinstance(s, dict)
    )
    assert "test_platform_compose_boot" in runs, (
        "platform-boot lane must actually run the compose-boot tests"
    )


def test_every_platform_preset_has_a_boot_test():
    presets = {d.name for d in _PLATFORMS_ROOT.iterdir() if (d / "platform.toml").is_file()}
    assert presets, "no --platform presets discovered — check the templates path"
    test_names = set(re.findall(r"^def (test_\w+)", _BOOT_TEST.read_text("utf-8"), re.M))
    missing = {
        preset
        for preset in presets
        if not any(preset.replace("-", "_") in name for name in test_names)
    }
    assert not missing, (
        f"--platform preset(s) {sorted(missing)} have no compose-boot test in "
        "tests/e2e/test_platform_compose_boot.py — add one (a new preset must boot "
        "in CI, or it can ship broken like multitenant-saas did)"
    )
