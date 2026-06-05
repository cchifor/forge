"""Smoke test for the worker loop.

Drives a bounded run (``max_iterations``) so the loop terminates and asserts
the iteration count matches — proving the entrypoint is importable and the
loop is coherent without waiting on real wall-clock sleeps.
"""

from __future__ import annotations

import pytest

from worker.config import WorkerSettings
from worker.worker import run


@pytest.mark.asyncio
async def test_worker_runs_bounded_iterations() -> None:
    settings = WorkerSettings(max_iterations=3, poll_interval_seconds=0.0)
    iterations = await run(settings)
    assert iterations == 3


@pytest.mark.asyncio
async def test_worker_single_iteration() -> None:
    settings = WorkerSettings(max_iterations=1, poll_interval_seconds=0.0)
    iterations = await run(settings)
    assert iterations == 1
