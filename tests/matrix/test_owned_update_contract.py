"""The nightly lane must detect destructive or incorrectly rejected updates."""

import subprocess

import pytest

from tests.matrix import update_contract


@pytest.mark.parametrize("mode", ["skip", "overwrite"])
@pytest.mark.parametrize("behavior", ["reject", "wrong_error", "mutate", "accept"])
def test_owned_mode_rejection_requires_the_right_error_and_unchanged_files(
    tmp_path, monkeypatch, mode, behavior
):
    source = tmp_path / "custom.py"
    source.write_text("custom code")
    calls = []

    def run_forge(args):
        calls.append(args)
        message = "Ownership-managed projects require a complete merge update"
        if behavior == "mutate":
            source.write_text("clobbered")
        if behavior == "wrong_error":
            message = "unrelated generation failure"
        code = 0 if behavior == "accept" else 2
        return subprocess.CompletedProcess(args, code, stdout="", stderr=message)

    monkeypatch.setattr(update_contract, "_run_forge", run_forge)
    error = update_contract._drive_rejected_owned_mode(tmp_path, mode)
    if behavior == "reject":
        assert error is None
        assert len(calls) == 2
        assert source.read_text() == "custom code"
    else:
        assert error is not None
        if behavior == "mutate":
            assert "custom.py" in error
