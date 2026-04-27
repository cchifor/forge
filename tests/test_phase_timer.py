"""Tests for ``forge.logging.phase_timer`` (Epic 4).

The timer is the foundation of generator telemetry. It must:
  - Emit one INFO-level log record per phase with ``duration_ms`` and
    ``status="ok"``.
  - Emit one WARNING-level record with ``status="failed"`` on
    exception, then re-raise.
  - Pass extra kwargs through to the structured-event payload.
"""

from __future__ import annotations

import logging

import pytest

from forge.logging import get_logger, phase_timer


def test_phase_timer_emits_ok_on_success(caplog: pytest.LogCaptureFixture) -> None:
    """Happy path: one INFO record with the event name + duration_ms."""
    logger = get_logger("test.phase_timer.ok")
    caplog.set_level(logging.INFO, logger="forge")
    with phase_timer(logger, "test.phase", backend="api"):
        pass

    matching = [r for r in caplog.records if getattr(r, "_forge_event", {}).get("event") == "test.phase"]
    assert len(matching) == 1
    fields = matching[0]._forge_event
    assert fields["status"] == "ok"
    assert fields["backend"] == "api"
    assert isinstance(fields["duration_ms"], int)
    assert fields["duration_ms"] >= 0


def test_phase_timer_emits_failed_on_exception(caplog: pytest.LogCaptureFixture) -> None:
    """Failure path: WARNING record with status=failed, then exception
    re-raises so callers don't accidentally swallow errors."""
    logger = get_logger("test.phase_timer.fail")
    caplog.set_level(logging.WARNING, logger="forge")

    with pytest.raises(RuntimeError, match="boom"):
        with phase_timer(logger, "test.phase.bad", backend="api"):
            raise RuntimeError("boom")

    matching = [
        r
        for r in caplog.records
        if getattr(r, "_forge_event", {}).get("event") == "test.phase.bad"
    ]
    assert len(matching) == 1
    fields = matching[0]._forge_event
    assert fields["status"] == "failed"
    assert fields["backend"] == "api"
    assert matching[0].levelno == logging.WARNING


def test_phase_timer_duration_increases(caplog: pytest.LogCaptureFixture) -> None:
    """A nontrivial phase records nontrivial duration. Anchors that
    perf_counter is wired correctly (otherwise duration would always
    be 0)."""
    import time as _time

    logger = get_logger("test.phase_timer.dur")
    caplog.set_level(logging.INFO, logger="forge")
    with phase_timer(logger, "test.phase.timed"):
        _time.sleep(0.02)

    matching = [
        r
        for r in caplog.records
        if getattr(r, "_forge_event", {}).get("event") == "test.phase.timed"
    ]
    assert len(matching) == 1
    # 20ms sleep should record at least 10ms even on a slow CI runner
    # — give 5ms headroom for sleep granularity.
    assert matching[0]._forge_event["duration_ms"] >= 10
