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

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
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

    api.add_fragment(
        Fragment(
            name="queue_port",
            # RFC-012 (Theme 7-C2/C3) — Python, Node, and Rust ports all
            # ship behind the same domain shape. With all three built-ins
            # covered, auto-derivation tags this as tier 1 cross-backend
            # parity. The explicit ``parity_tier=2`` override that used to
            # live here is dropped now that the Rust impl has landed.
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("queue_port", "python"),
                ),
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("queue_port", "node"),
                ),
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("queue_port", "rust"),
                    # The port itself uses async_trait + futures + serde +
                    # thiserror in its trait/struct declarations; landing
                    # the port without these deps would fail ``cargo
                    # check`` even before any adapter wires in.
                    dependencies=(
                        'async-trait = "0.1"',
                        'futures = "0.3"',
                        'serde = { version = "1", features = ["derive"] }',
                        'serde_json = "1"',
                        'thiserror = "1"',
                    ),
                ),
            },
        )
    )

    api.add_fragment(
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

    api.add_fragment(
        Fragment(
            name="queue_bullmq",
            # RFC-012 (Theme 7-C2) — BullMQ adapter for Node. Node-only by
            # design: BullMQ is a Node-native queue library. Auto-derives as
            # tier 3, which is the correct label — see RFC-012's
            # "Promotion to tier-1" section: tier-3 here means "adapter is
            # language-specific by design", not "feature is Python-only".
            depends_on=("queue_port",),
            capabilities=("redis",),
            implementations={
                BackendLanguage.NODE: FragmentImplSpec(
                    fragment_dir=_impl("queue_bullmq", "node"),
                    dependencies=("bullmq@5.30.0", "ioredis@5.4.1"),
                    env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="queue_apalis",
            # RFC-012 (Theme 7-C3) — Apalis adapter for Rust. Rust-only by
            # design: Apalis is a Rust-native job framework. Auto-derives
            # as tier 3, which is the correct label — see RFC-012's
            # "Promotion to tier-1" section: tier-3 here means "adapter is
            # language-specific by design", not "feature is Python-only".
            depends_on=("queue_port",),
            capabilities=("redis",),
            implementations={
                BackendLanguage.RUST: FragmentImplSpec(
                    fragment_dir=_impl("queue_apalis", "rust"),
                    # Adapter-specific deps only — async-trait/futures/serde/
                    # serde_json/thiserror come in via the queue_port/rust
                    # impl this fragment depends on.
                    dependencies=(
                        "apalis@0.6",
                        "apalis-redis@0.6",
                        'async-stream = "0.3"',
                        'chrono = "0.4"',
                        'tokio = { version = "1", features = ["sync", "time"] }',
                        'uuid = { version = "1", features = ["v4"] }',
                    ),
                    env_vars=(("TASKIQ_BROKER_URL", "redis://redis:6379/2"),),
                ),
            },
        )
    )

    api.add_fragment(
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
