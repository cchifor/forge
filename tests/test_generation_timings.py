"""generate(report=...) must populate per-phase timings in the --json payload.

Generation timing was previously log-only (phase_timer emitted duration_ms to
logs but nothing reached the GenerationReport). This wires it into
report.phase_timings via a scoped PhaseHook."""

from __future__ import annotations

from pathlib import Path

from forge import hooks
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate
from forge.reports import GenerationReport


def _cfg(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_name="timings",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="api", project_name="timings", language=BackendLanguage.PYTHON, features=["items"]
            )
        ],
        options={},
    )


def test_report_carries_phase_timings(tmp_path):
    rpt = GenerationReport()
    generate(_cfg(tmp_path), quiet=True, report=rpt)
    assert rpt.phase_timings, "phase_timings should be populated"
    # The headline phases must be present.
    assert any(k.startswith("generate.") for k in rpt.phase_timings)
    assert all(isinstance(v, int) and v >= 0 for v in rpt.phase_timings.values())
    assert "phase_timings" in rpt.to_dict()


def test_no_report_means_no_timing_overhead(tmp_path):
    # report=None must not register a hook (zero-overhead path preserved).
    before = len(hooks.registered_hooks())
    generate(_cfg(tmp_path), quiet=True)  # no report
    assert len(hooks.registered_hooks()) == before


def test_timings_hook_does_not_leak(tmp_path):
    before = len(hooks.registered_hooks())
    generate(_cfg(tmp_path), quiet=True, report=GenerationReport())
    assert len(hooks.registered_hooks()) == before, "the timings hook must be unregistered"
