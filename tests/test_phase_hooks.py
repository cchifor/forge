"""Tests for :mod:`forge.hooks` — the Pillar A.3 ``PhaseHook`` protocol.

Covers:

* hooks fire in registration order on ``phase_timer`` enter / exit,
  with the right phase name + context dict;
* a buggy hook (raises in any callback) does NOT break the timer
  itself, does NOT block other hooks, and does NOT crash a real
  ``generate()`` run;
* ``on_generate_complete`` fires exactly once at the end of
  ``generate()``, with the populated ``GenerationReport`` (or ``None``
  when the caller didn't supply one);
* ``ForgeAPI.add_hook`` is the public registration entry point and
  delegates to :func:`forge.hooks.register_hook`.

The fake hook records every callback into per-instance lists so
tests assert on shape + order. ``reset_hooks_for_tests`` runs in an
autouse fixture so registrations don't leak between tests in the
same pytest-xdist worker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from forge.api import ForgeAPI, PluginRegistration
from forge.config import BackendConfig, ProjectConfig
from forge.generator import generate
from forge.hooks import (
    PhaseHook,
    _fire_generate_complete,
    _fire_phase_end,
    _fire_phase_start,
    register_hook,
    registered_hooks,
    reset_hooks_for_tests,
)
from forge.logging import get_logger, phase_timer
from forge.reports import GenerationReport


@dataclass
class _RecordingHook:
    """Fake hook that records every callback for assertion.

    Implements :class:`PhaseHook` structurally. ``name`` distinguishes
    instances when tests register more than one to assert ordering.
    """

    name: str = "rec"
    starts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    ends: list[tuple[str, dict[str, Any], int, Exception | None]] = field(default_factory=list)
    completes: list[GenerationReport | None] = field(default_factory=list)

    def on_phase_start(self, name: str, ctx: dict[str, Any]) -> None:
        # Capture a shallow copy of ``ctx`` so a later mutation by the
        # caller (or by the contract violation we explicitly forbid in
        # the PhaseHook docstring) doesn't poison our assertion.
        self.starts.append((name, dict(ctx)))

    def on_phase_end(
        self,
        name: str,
        ctx: dict[str, Any],
        duration_ms: int,
        error: Exception | None,
    ) -> None:
        self.ends.append((name, dict(ctx), duration_ms, error))

    def on_generate_complete(self, report: GenerationReport | None) -> None:
        self.completes.append(report)


class _RaisingHook:
    """A buggy hook that raises in every callback.

    The contract under test: this MUST NOT break generation, MUST NOT
    suppress other hooks from firing, and the original exception (when
    the timed block itself raised) MUST still propagate.
    """

    def on_phase_start(self, name: str, ctx: dict[str, Any]) -> None:
        raise RuntimeError(f"buggy on_phase_start for {name!r}")

    def on_phase_end(
        self,
        name: str,
        ctx: dict[str, Any],
        duration_ms: int,
        error: Exception | None,
    ) -> None:
        raise RuntimeError(f"buggy on_phase_end for {name!r}")

    def on_generate_complete(self, report: GenerationReport | None) -> None:
        raise RuntimeError("buggy on_generate_complete")


@pytest.fixture(autouse=True)
def _reset_hooks() -> None:
    """Per-test isolation of the module-level hook registry."""
    reset_hooks_for_tests()


# -- Protocol structural conformance ---------------------------------------


def test_recording_hook_satisfies_protocol() -> None:
    """``@runtime_checkable Protocol`` should accept the structural fake.

    Anchors the contract that plugin authors don't need to subclass —
    duck-typing ``on_phase_*`` + ``on_generate_complete`` is enough.
    """
    hook = _RecordingHook()
    assert isinstance(hook, PhaseHook)


# -- Direct fire-helper tests (no generator) -------------------------------


class TestFireHelpers:
    def test_registration_order_is_firing_order(self) -> None:
        first = _RecordingHook(name="first")
        second = _RecordingHook(name="second")
        register_hook(first)
        register_hook(second)

        assert registered_hooks() == (first, second)

        _fire_phase_start("test.phase", {"backend": "api"})
        assert first.starts == [("test.phase", {"backend": "api"})]
        assert second.starts == [("test.phase", {"backend": "api"})]

    def test_raising_start_hook_does_not_block_siblings(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A hook raising in on_phase_start MUST NOT break later hooks."""
        raiser = _RaisingHook()
        recorder = _RecordingHook()
        register_hook(raiser)
        register_hook(recorder)

        # The fire helper itself returns normally — no exception bubbles
        # out, even though the first hook raised inside it.
        _fire_phase_start("test.phase", {"backend": "api"})

        assert recorder.starts == [("test.phase", {"backend": "api"})]
        # Diagnostic surface: the swallow path logs at WARNING with the
        # hook class name in the message, so operators can trace which
        # plugin is misbehaving.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("_RaisingHook" in r.getMessage() for r in warnings)

    def test_raising_end_hook_does_not_block_siblings(self) -> None:
        raiser = _RaisingHook()
        recorder = _RecordingHook()
        register_hook(raiser)
        register_hook(recorder)

        _fire_phase_end("test.phase", {"backend": "api"}, 42, None)

        assert recorder.ends == [("test.phase", {"backend": "api"}, 42, None)]

    def test_raising_generate_complete_does_not_block_siblings(self) -> None:
        raiser = _RaisingHook()
        recorder = _RecordingHook()
        register_hook(raiser)
        register_hook(recorder)

        report = GenerationReport(project_root="/tmp/x")
        _fire_generate_complete(report)

        assert recorder.completes == [report]

    def test_generate_complete_propagates_none(self) -> None:
        """When the caller didn't supply a report, hooks see ``None``."""
        recorder = _RecordingHook()
        register_hook(recorder)

        _fire_generate_complete(None)

        assert recorder.completes == [None]


# -- phase_timer integration -----------------------------------------------


class TestPhaseTimerFiresHooks:
    def test_success_path_fires_start_then_end_with_zero_error(self) -> None:
        recorder = _RecordingHook()
        register_hook(recorder)
        logger = get_logger("test.phase_hooks.ok")

        with phase_timer(logger, "test.phase", backend="api", language="python"):
            pass

        assert recorder.starts == [
            ("test.phase", {"backend": "api", "language": "python"}),
        ]
        assert len(recorder.ends) == 1
        end_name, end_ctx, duration_ms, error = recorder.ends[0]
        assert end_name == "test.phase"
        assert end_ctx == {"backend": "api", "language": "python"}
        assert error is None
        assert isinstance(duration_ms, int)
        assert duration_ms >= 0

    def test_failure_path_fires_end_with_exception_then_reraises(self) -> None:
        recorder = _RecordingHook()
        register_hook(recorder)
        logger = get_logger("test.phase_hooks.fail")

        with (
            pytest.raises(RuntimeError, match="boom"),
            phase_timer(logger, "test.phase.bad", backend="api"),
        ):
            raise RuntimeError("boom")

        # start fired exactly once
        assert recorder.starts == [("test.phase.bad", {"backend": "api"})]
        # end fired exactly once, with the raised exception forwarded
        assert len(recorder.ends) == 1
        _, _, _, error = recorder.ends[0]
        assert isinstance(error, RuntimeError)
        assert str(error) == "boom"

    def test_buggy_hook_does_not_break_phase_timer(self) -> None:
        """phase_timer MUST yield through to the with-body even when a
        registered hook raises in on_phase_start. The block runs to
        completion; the timer emits its log normally."""
        register_hook(_RaisingHook())

        body_ran = False
        logger = get_logger("test.phase_hooks.bug")
        with phase_timer(logger, "test.phase", backend="api"):
            body_ran = True

        assert body_ran is True

    def test_phase_error_plus_hook_error_in_on_phase_end_reraises_phase(self) -> None:
        """Codex Phase B round 1 follow-up: the exception-handling contract
        must hold under the combined scenario "phase raises AND a hook raises
        while handling on_phase_end(error)". The original phase exception
        must re-raise unchanged; the hook-side exception must be swallowed
        the same way as it would be on a clean phase.
        """

        class _OnEndRaisingHook:
            def on_phase_start(self, name, ctx):  # noqa: D401 - protocol shim
                pass

            def on_phase_end(self, name, ctx, duration_ms, error):  # noqa: D401
                raise RuntimeError("hook-side boom in on_phase_end")

            def on_generate_complete(self, report):  # noqa: D401
                pass

        register_hook(_OnEndRaisingHook())
        logger = get_logger("test.phase_hooks.combined")

        with (
            pytest.raises(RuntimeError, match="phase boom") as excinfo,
            phase_timer(logger, "test.phase.combined", backend="api"),
        ):
            raise RuntimeError("phase boom")

        # The PHASE error is what re-raises — not the hook's error.
        assert str(excinfo.value) == "phase boom"
        assert "hook-side" not in str(excinfo.value)


# -- ForgeAPI.add_hook + end-to-end generate() ------------------------------


def _minimal_python_config(tmp_path) -> ProjectConfig:
    """Construct the smallest config that can be threaded through generate().

    Single Python backend, no frontend, no Keycloak — the goal is a
    fast end-to-end run in dry-run mode (skipping toolchain.install)
    so we can assert on hook firing without burning seconds on
    ``uv sync``.
    """
    bc = BackendConfig(project_name="HookProbe", server_port=5000)
    return ProjectConfig(
        project_name="HookProbe",
        backends=[bc],
        output_dir=str(tmp_path),
    )


class TestAddHookEndToEnd:
    def test_add_hook_delegates_to_module_registry(self) -> None:
        recorder = _RecordingHook()
        api = ForgeAPI(PluginRegistration(name="p", module="m"))
        api.add_hook(recorder)
        assert registered_hooks() == (recorder,)

    def test_generate_fires_hooks_for_each_phase(self, tmp_path) -> None:
        """A real (dry-run) generate() fires start/end for every phase
        and on_generate_complete exactly once at the end."""
        recorder = _RecordingHook()
        register_hook(recorder)

        config = _minimal_python_config(tmp_path)
        config.validate()
        project_root = generate(config, quiet=True, dry_run=True)
        assert project_root.exists()

        # Every phase fires balanced start/end pairs.
        assert len(recorder.starts) >= 1
        assert len(recorder.starts) == len(recorder.ends)
        start_names = [name for name, _ in recorder.starts]
        end_names = [name for name, _, _, _ in recorder.ends]
        assert start_names == end_names

        # The canonical phases the brief points at — resolve, validate,
        # copier.backend, apply_features, write_forge_toml — should all
        # appear. We don't assert the full set (future generator phases
        # may grow), just that these load-bearing ones fire.
        assert "generate.resolve" in start_names
        assert "generate.validate_plan" in start_names
        assert "generate.copier.backend" in start_names
        assert "generate.apply_features" in start_names
        assert "generate.write_forge_toml" in start_names

        # All durations are non-negative ints; all errors are None on
        # the happy path.
        for _, _, duration_ms, error in recorder.ends:
            assert isinstance(duration_ms, int)
            assert duration_ms >= 0
            assert error is None

        # on_generate_complete fires exactly once. ``report=None`` was
        # passed, so the hook sees None — this is the legacy zero-overhead
        # path documented on generate().
        assert recorder.completes == [None]

    def test_generate_forwards_report_to_hook(self, tmp_path) -> None:
        recorder = _RecordingHook()
        register_hook(recorder)

        config = _minimal_python_config(tmp_path)
        config.validate()
        report = GenerationReport()
        generate(config, quiet=True, dry_run=True, report=report)

        # on_generate_complete fires exactly once with the populated
        # report (not None, not a different instance).
        assert len(recorder.completes) == 1
        assert recorder.completes[0] is report
        # The report was actually populated — sanity-check one field
        # _populate_report writes.
        assert report.project_root != ""

    def test_buggy_hook_does_not_crash_generate(self, tmp_path) -> None:
        """The hard contract: a buggy plugin MUST NOT break generation.

        Registers a raising hook FIRST so it fires before the recorder
        on every callback, plus a recorder that has to still receive
        every callback for the run to be considered fully observable.
        """
        register_hook(_RaisingHook())
        recorder = _RecordingHook()
        register_hook(recorder)

        config = _minimal_python_config(tmp_path)
        config.validate()

        # Generation must complete without raising.
        project_root = generate(config, quiet=True, dry_run=True)
        assert project_root.exists()

        # Recorder still observed every callback — the raising hook
        # didn't poison the iteration.
        assert len(recorder.starts) >= 1
        assert len(recorder.starts) == len(recorder.ends)
        assert recorder.completes == [None]
