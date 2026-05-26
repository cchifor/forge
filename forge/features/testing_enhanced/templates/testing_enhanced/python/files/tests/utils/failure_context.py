"""Failure forensics — capture structured context on test failures.

On any test failure, writes a JSON file to ``tests/.failure-context/<test-id>/``
with timestamps, environment info, and (when available) CI metadata. This
enables post-mortem debugging without reproducing the failure locally.

Usage
-----
Register this module as a pytest plugin by adding it to the root
``tests/conftest.py``::

    from tests.utils.failure_context import failure_context_emitter  # noqa: F401

    pytest_plugins = ["tests.utils.failure_context"]

Or add to ``pyproject.toml``::

    [tool.pytest.ini_options]
    plugins = ["tests.utils.failure_context"]
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import pytest


def _ci_metadata() -> dict[str, str | None]:
    """Collect CI environment markers (GitHub Actions)."""
    return {
        "ci": os.environ.get("CI"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "github_ref": os.environ.get("GITHUB_REF"),
    }


def _build_context(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Build the failure context payload."""
    return {
        "test_id": request.node.nodeid,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "ci": _ci_metadata(),
        "markers": [str(m) for m in request.node.iter_markers()],
    }


@pytest.fixture(scope="session")
def failure_context_emitter():
    """Fixture that returns a callable to emit failure context JSON."""
    output_dir = Path("tests/.failure-context")

    def emit(request: pytest.FixtureRequest) -> None:
        ctx = _build_context(request)
        safe_id = request.node.nodeid.replace("/", "_").replace("::", "__")
        dest = output_dir / safe_id
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "failure-context.json").write_text(
            json.dumps(ctx, indent=2, default=str),
            encoding="utf-8",
        )

    return emit


@pytest.fixture(autouse=True)
def _emit_failure_context(request: pytest.FixtureRequest, failure_context_emitter):
    """Autouse fixture — emits failure context when a test fails."""
    yield
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        failure_context_emitter(request)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):  # noqa: ARG001
    """Stash the call report on the test item for fixture access."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
