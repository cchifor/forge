"""generated-quality resolves rendered npm applications reproducibly.

Rendered Node/Vue/Svelte applications ship ranged manifests and no lockfile.
Required pull-request and push runs resolve them as of a recorded registry
snapshot; the weekly scheduled run resolves them live and reports drift.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

_WORKFLOW = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "generated-quality.yml"
)


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def test_required_runs_resolve_npm_as_of_a_recorded_past_snapshot() -> None:
    workflow = _workflow()
    snapshot = dt.datetime.fromisoformat(workflow["env"]["FORGE_NPM_SNAPSHOT"])
    assert snapshot.utcoffset() == dt.timedelta(0)
    assert snapshot <= dt.datetime.now(dt.UTC)
    steps = workflow["jobs"]["rendered"]["steps"]
    exports = [i for i, step in enumerate(steps) if "npm_config_before" in step.get("run", "")]
    gate = next(
        i for i, step in enumerate(steps) if "check_generated_quality.py" in step.get("run", "")
    )
    assert len(exports) == 1 and exports[0] < gate
    step = steps[exports[0]]
    assert step["run"] == 'echo "npm_config_before=$FORGE_NPM_SNAPSHOT" >> "$GITHUB_ENV"'
    assert step["if"] == "github.event_name == 'pull_request' || github.event_name == 'push'"


def test_the_scheduled_canary_resolves_live_without_cancelling_required_runs() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))  # YAML 1.1 reads a bare `on` as true
    assert {"pull_request", "push", "schedule"} <= set(triggers)
    assert triggers["schedule"][0]["cron"]
    assert "github.event_name" in workflow["concurrency"]["group"]
