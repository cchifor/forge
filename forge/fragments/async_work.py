"""Async/background-work fragments — off-thread job processing.

``background_tasks`` ships a per-backend job queue: TaskIQ on Python,
BullMQ on Node, Apalis on Rust — all backed by Redis so the
``capabilities=("redis",)`` registration triggers a Redis sidecar in
docker-compose.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="background_tasks",
        capabilities=("redis",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="background_tasks/python",
                dependencies=("taskiq>=0.11.0", "taskiq-redis>=1.0.0"),
                env_vars=(
                    ("TASKIQ_BROKER_URL", "redis://redis:6379/2"),
                    ("TASKIQ_RESULT_BACKEND_URL", "redis://redis:6379/2"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="background_tasks/node",
                dependencies=("bullmq@5.30.0", "ioredis@5.4.1"),
                env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="background_tasks/rust",
                dependencies=("apalis@0.6", "apalis-redis@0.6"),
                env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
            ),
        },
    )
)
