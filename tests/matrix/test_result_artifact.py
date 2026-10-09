"""Nightly artifacts must describe the gated execution, including its failure."""

import json
import sys

import pytest

from tests.matrix import runner


@pytest.mark.parametrize("status,exit_code", [("ok", 0), ("fail", 2)])
def test_artifact_records_one_execution_without_log_contamination(
    tmp_path, monkeypatch, capsys, status, exit_code
):
    scenario = runner.Scenario("probe", "probe", ("update",), 8000, (), {})
    artifact = tmp_path / "reports" / "probe.json"
    calls = []

    def execute(actual, lane):
        calls.append((actual.name, lane))
        print("Noisy build output is not JSON")
        return runner.LaneResult(actual.name, lane, status, 123, "original execution")

    monkeypatch.setattr(runner, "load_scenarios", lambda: [scenario])
    monkeypatch.setattr(runner, "run_scenario", execute)
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--scenario", "probe", "--lane", "update", "--json-output", str(artifact)],
    )
    assert runner.main() == exit_code
    assert calls == [("probe", "update")]
    assert json.loads(artifact.read_text()) == [
        {
            "scenario": "probe",
            "lane": "update",
            "status": status,
            "duration_ms": 123,
            "details": "original execution",
            "missing_files": [],
            "skipped_subchecks": [],
        }
    ]
    assert "Noisy build output" in capsys.readouterr().out
