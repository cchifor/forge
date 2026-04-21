"""ty canary: isolate upstream ty regressions from forge regressions.

``tests/fixtures/ty_canary/`` ships 12 small Python files exercising the
five ty rules forge depends on (``unresolved-import``,
``invalid-argument-type``, ``invalid-return-type``, ``missing-argument``,
``unknown-argument``) plus inference smoke tests for TypedDict and
generic Protocol.

This test runs ``uv run ty check`` against those fixtures and verifies
that each file produces exactly the diagnostic its header annotates
(``# expect: error[<rule-id>]`` or ``# expect: ok``). A divergence means
ty's behaviour changed — forge's pinned version in ``pyproject.toml``
needs to move via a ``.github/workflows/ty-upgrade.yml`` run before the
CI typecheck job is trustworthy again.

Invariants:
- Every fixture file starts with ``# expect: ...`` on line 1.
- ``# expect: ok`` → ty reports zero diagnostics on that file.
- ``# expect: error[<rule>]`` → ty reports at least one diagnostic of
  exactly that rule on that file.

The test is intentionally subprocess-based rather than importing ty's
Python API — Astral treats ty as a CLI and the alpha Python bindings
change between releases.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ty_canary"
ERROR_HEADER_RE = re.compile(r"^# expect: error\[([\w-]+)\]\s*$")
OK_HEADER_RE = re.compile(r"^# expect: ok\s*$")
# ty's diagnostic output lines look like `error[rule-id]: <msg>` on the
# first line of each diagnostic. We parse those for the rule id.
TY_DIAG_LINE_RE = re.compile(r"^error\[([\w-]+)\]")


def _fixtures() -> list[Path]:
    """Return every ``rule_*.py`` or ``inference_*.py`` fixture, sorted."""
    files = sorted(
        f
        for f in FIXTURES_DIR.glob("*.py")
        if f.name != "__init__.py"
    )
    if not files:
        pytest.fail(
            f"No canary fixtures found under {FIXTURES_DIR}. The canary "
            f"directory is empty or the path is wrong."
        )
    return files


def _parse_expectation(fixture: Path) -> tuple[str, str | None]:
    """Return ``('error', rule_id)`` or ``('ok', None)`` from the file header."""
    line = fixture.read_text(encoding="utf-8").splitlines()[0]
    m = ERROR_HEADER_RE.match(line)
    if m:
        return "error", m.group(1)
    if OK_HEADER_RE.match(line):
        return "ok", None
    pytest.fail(
        f"{fixture.name}: first line must be '# expect: ok' or "
        f"'# expect: error[<rule>]' — got {line!r}"
    )


def _run_ty(fixture: Path) -> tuple[int, str]:
    """Invoke ``ty check <fixture>`` and return ``(exit_code, combined_output)``."""
    # Prefer `uv run ty` because that's what CI runs; fall back to a bare
    # `ty` on the PATH if uv isn't available (e.g. ad-hoc local runs).
    uv = shutil.which("uv")
    if uv is not None:
        cmd = [uv, "run", "ty", "check", str(fixture)]
    else:
        ty = shutil.which("ty")
        if ty is None:
            pytest.skip("neither `uv` nor `ty` is on PATH; cannot run the canary")
        cmd = [ty, "check", str(fixture)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout + result.stderr


def _extracted_rule_ids(output: str) -> list[str]:
    """Return the list of rule ids that appear in ty's diagnostic output."""
    return [m.group(1) for line in output.splitlines() if (m := TY_DIAG_LINE_RE.match(line))]


def test_fixtures_dir_has_canary_files() -> None:
    """Smoke test: if the canary dir is empty, the regression detector is off."""
    files = _fixtures()
    # At least one 'error' and one 'ok' fixture must exist or the canary
    # is checking nothing meaningful.
    have_error = any(_parse_expectation(f)[0] == "error" for f in files)
    have_ok = any(_parse_expectation(f)[0] == "ok" for f in files)
    assert have_error, "No `# expect: error[...]` fixtures — error detection is unverified"
    assert have_ok, "No `# expect: ok` fixtures — clean-code behaviour is unverified"


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda p: p.name)
def test_canary_fixture_matches_expectation(fixture: Path) -> None:
    """Each canary fixture produces the diagnostic its header promises."""
    expectation, expected_rule = _parse_expectation(fixture)
    exit_code, output = _run_ty(fixture)
    rules = _extracted_rule_ids(output)

    if expectation == "ok":
        assert not rules, (
            f"{fixture.name}: expected no diagnostics, got {rules}. "
            f"Full output:\n{output}"
        )
        return

    assert expected_rule is not None  # for ty: header parser guarantees this
    assert expected_rule in rules, (
        f"{fixture.name}: expected diagnostic rule `{expected_rule}`, "
        f"got {rules}. ty's behaviour may have changed — bump the pin "
        f"via .github/workflows/ty-upgrade.yml after investigating.\n"
        f"Full output:\n{output}"
    )
    # Exit code sanity: ty exits non-zero when it reports errors.
    assert exit_code != 0, (
        f"{fixture.name}: ty reported `{expected_rule}` but exited 0. "
        f"That's a ty bug — the canary just caught it."
    )
