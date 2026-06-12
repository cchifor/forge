"""Guard: a failed scheduled nightly must notify someone (#217).

A red nightly that dies silently in the Actions tab is exactly how regressions
ship unnoticed (the recurring WS lesson). Both heavyweight scheduled nightlies
— ``matrix-nightly`` and the unfiltered ``e2e-nightly-full`` lane — must carry a
notify-on-failure job that:

* fires ONLY on ``schedule`` (so PR / workflow_dispatch / label runs never spam
  the issue tracker),
* runs on failure of the real work, and
* has ``issues: write`` so it can open / comment the ``nightly-failure``
  tracking issue.

This mechanizes the fix so a future workflow edit can't quietly drop the
notification.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _load(workflow: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / workflow).read_text(encoding="utf-8"))


def _notify_jobs(jobs: dict) -> dict[str, dict]:
    return {name: job for name, job in jobs.items() if "notify" in name}


@pytest.mark.parametrize(
    ("workflow", "work_job"),
    [
        ("matrix-nightly.yml", "smoke"),
        ("e2e.yml", "e2e-nightly-full"),
    ],
)
def test_scheduled_nightly_has_failure_notifier(workflow: str, work_job: str) -> None:
    jobs = _load(workflow)["jobs"]
    notifiers = _notify_jobs(jobs)
    assert notifiers, (
        f"{workflow} has no notify-on-failure job — a scheduled nightly that "
        "fails would notify nobody (#217)"
    )
    job = next(iter(notifiers.values()))

    cond = job.get("if", "")
    assert "schedule" in cond, (
        f"{workflow} notifier must gate on github.event_name == 'schedule' so "
        f"PR/dispatch runs don't open issues; got if: {cond!r}"
    )
    assert "failure" in cond, f"{workflow} notifier must only fire on failure; got if: {cond!r}"

    # It must depend on the real work job so its result is observable.
    needs = job.get("needs", [])
    needs = [needs] if isinstance(needs, str) else needs
    assert work_job in needs, (
        f"{workflow} notifier must `needs: {work_job}` to react to its result; got {needs}"
    )

    # It needs issue-write to open/comment the tracking issue.
    perms = job.get("permissions", {})
    assert isinstance(perms, dict) and perms.get("issues") == "write", (
        f"{workflow} notifier needs `permissions: issues: write`; got {perms}"
    )
