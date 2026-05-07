"""Async job queue powered by Taskiq.

Import ``broker`` from this package to decorate functions as tasks. Run a
worker with ``uv run taskiq worker app.worker:broker`` — tasks execute
out-of-process so request handlers stay fast.
"""

from app.worker.broker import broker
from app.worker.tasks import hello_task

__all__ = ["broker", "hello_task"]
