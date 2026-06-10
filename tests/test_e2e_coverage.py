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

_E2E_YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "e2e.yml"


def _load_jobs() -> dict:
    return yaml.safe_load(_E2E_YML.read_text(encoding="utf-8"))["jobs"]


def test_unfiltered_nightly_job_exists():
    jobs = _load_jobs()
    assert "e2e-nightly-full" in jobs, (
        "the full-e2e nightly job is missing — without it ~80% of e2e tests "
        "run in no workflow"
    )


def test_nightly_job_runs_e2e_without_k_filter():
    job = _load_jobs()["e2e-nightly-full"]
    run_steps = [
        s.get("run", "") for s in job["steps"] if isinstance(s, dict) and "run" in s
    ]
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
    run = " ".join(
        s.get("run", "") for s in job["steps"] if isinstance(s, dict) and "run" in s
    )
    assert "-rs" in run, "use `pytest -rs` so env-gated e2e skips are visible"
