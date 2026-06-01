"""WS-8.1: the dependency security scan must be a blocking CI gate.

The security-scan job ran with ``continue-on-error: true`` and its npm audit
ended in ``|| true`` — so high/critical CVEs never failed CI. Make it block
(pip-audit already exits non-zero on a finding; npm audit --audit-level=high
must not be neutralised).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _security_job() -> dict:
    doc = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert "security-scan" in jobs, "security-scan job missing from ci.yml"
    return jobs["security-scan"]


def test_security_scan_is_not_advisory():
    job = _security_job()
    assert job.get("continue-on-error") in (None, False), (
        "security-scan must block CI (no continue-on-error: true)"
    )


def test_npm_audit_not_neutralised():
    raw = _CI.read_text(encoding="utf-8")
    # The whole security-scan region must not swallow npm audit failures.
    job = _security_job()
    steps_text = yaml.dump(job)
    assert "npm audit" in steps_text, "npm audit step should still exist"
    assert "|| true" not in steps_text, "npm audit must not be neutralised with '|| true'"
    assert "--audit-level=high" in steps_text, "npm audit must gate at high severity"
