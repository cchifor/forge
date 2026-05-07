"""Async/background-work fragments — off-thread job processing.

``background_tasks`` ships a per-backend job queue: TaskIQ on Python,
BullMQ on Node, Apalis on Rust — all backed by Redis so the
``capabilities=("redis",)`` registration triggers a Redis sidecar in
docker-compose.

``queue_port`` defines the abstract message-queue interface; adapters
plug in concrete implementations. Tier 2 (committed migration target)
— Rust adapters pending per RFC-006.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


register_fragment(
    Fragment(
        name="background_tasks",
        capabilities=("redis",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("background_tasks", "python"),
                dependencies=("taskiq>=0.11.0", "taskiq-redis>=1.0.0"),
                env_vars=(
                    ("TASKIQ_BROKER_URL", "redis://redis:6379/2"),
                    ("TASKIQ_RESULT_BACKEND_URL", "redis://redis:6379/2"),
                ),
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir=_impl("background_tasks", "node"),
                dependencies=("bullmq@5.30.0", "ioredis@5.4.1"),
                env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir=_impl("background_tasks", "rust"),
                dependencies=("apalis@0.6", "apalis-redis@0.6"),
                env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="queue_port",
        # Explicit tier=2 override: this is a committed migration target
        # to tier 1 (Rust adapter pending — see RFC-006). Auto-derive
        # would tag it as tier 3 (Python-only), which understates the
        # intent.
        parity_tier=2,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("queue_port", "python"),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="queue_redis",
        depends_on=("queue_port",),
        capabilities=("redis",),
        # See queue_port — tier=2 migration target. The Rust adapter
        # will layer on top of queue_port/rust once it lands.
        parity_tier=2,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("queue_redis", "python"),
                dependencies=("redis>=5.2.0",),
                env_vars=(("REDIS_URL", "redis://redis:6379/0"),),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="queue_sqs",
        depends_on=("queue_port",),
        # SQS from Rust is possible via aws-sdk-sqs but not prioritized
        # — keep tier=3 (auto). Staying explicit here documents that
        # we *considered* bumping to tier 2 and chose not to.
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("queue_sqs", "python"),
                dependencies=("aioboto3>=13.2.0",),
                env_vars=(("AWS_REGION", "us-east-1"),),
            ),
        },
    )
)
