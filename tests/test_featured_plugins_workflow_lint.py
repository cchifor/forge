"""Lint guard for ``.github/workflows/featured-plugins-e2e.yml`` (Pillar D.4).

The workflow is a low-traffic file — it only runs on a nightly cron and
on ``workflow_dispatch``. That makes it an easy target for accidental
removal or "I didn't think anything cared about this trigger" edits by
codemod / lint-fix tools. This test parses the YAML and asserts the
load-bearing pieces are intact:

* nightly ``schedule:`` cron trigger,
* ``workflow_dispatch`` manual trigger,
* a non-empty matrix (so the workflow renders even with zero curated
  plugins — see the docs/plugin-development.md "Featured Plugin tier"
  section for the empty-matrix-by-design rationale),
* ``actions/checkout@v4`` pinned at major-version granularity.

If you genuinely need to delete or rewrite the workflow, delete or
rewrite this test in the same commit. The point is that you have to
say so out loud.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "featured-plugins-e2e.yml"
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    if not WORKFLOW_PATH.is_file():
        pytest.fail(
            f"Featured-plugin workflow missing at {WORKFLOW_PATH}. "
            "If this is intentional, delete tests/test_featured_plugins_workflow_lint.py "
            "in the same commit and remove the Featured Plugin tier section from "
            "docs/plugin-development.md."
        )
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_schedule_trigger_present(workflow: dict) -> None:
    # PyYAML parses the bare ``on:`` key as Python ``True`` because of
    # the YAML 1.1 boolean alias. Accept either form so a future YAML
    # 1.2 parser swap doesn't false-fail this test.
    on = workflow.get("on") or workflow.get(True)
    assert on is not None, "workflow has no triggers"
    assert "schedule" in on, "nightly cron trigger missing"
    schedule = on["schedule"]
    assert isinstance(schedule, list) and schedule, "schedule must be a non-empty list"
    assert any("cron" in entry for entry in schedule), "schedule entries must declare cron expressions"


def test_workflow_dispatch_trigger_present(workflow: dict) -> None:
    on = workflow.get("on") or workflow.get(True)
    assert on is not None, "workflow has no triggers"
    assert "workflow_dispatch" in on, (
        "workflow_dispatch trigger missing — required so maintainers can "
        "re-run the nightly tier on demand after a flaky run."
    )


def test_matrix_has_placeholder_entry(workflow: dict) -> None:
    jobs = workflow.get("jobs", {})
    assert jobs, "workflow has no jobs"
    # Single-job workflow today; iterate so adding a second job later
    # doesn't silently invalidate this guard.
    matrix_jobs = [
        job for job in jobs.values()
        if isinstance(job, dict) and "strategy" in job and "matrix" in job["strategy"]
    ]
    assert matrix_jobs, "no job declares a strategy.matrix"
    for job in matrix_jobs:
        matrix = job["strategy"]["matrix"]
        # The placeholder convention is a ``plugin:`` list whose first
        # entry has ``enabled: false``. We only assert the list is
        # non-empty — the empty-matrix-by-design rationale lives in
        # docs/plugin-development.md, not in this guard.
        plugin_entries = matrix.get("plugin")
        assert plugin_entries, "matrix.plugin must contain at least a placeholder row"
        assert isinstance(plugin_entries, list)


def test_checkout_action_pinned_to_v4(workflow: dict) -> None:
    jobs = workflow.get("jobs", {})
    found_checkout = False
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            uses = step.get("uses", "") if isinstance(step, dict) else ""
            if uses.startswith("actions/checkout@"):
                found_checkout = True
                # Accept ``@v4`` or ``@v4.x.y`` or a pinned SHA followed
                # by a ``# v4.x.y`` comment. Reject ``@v3`` / ``@master``
                # / unpinned ``@main``.
                ref = uses.split("@", 1)[1]
                assert (
                    ref.startswith("v4")
                    or "# v4" in step.get("uses", "")  # SHA + comment form
                    or len(ref) == 40  # raw SHA — caller responsible for v4
                ), f"actions/checkout must be pinned to v4, got: {uses}"
    assert found_checkout, "workflow must use actions/checkout at least once"
