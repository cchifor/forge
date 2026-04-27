"""Queue port + adapters (1.0.0a2+).

``queue_port`` defines the abstract message-queue interface; adapters
plug in concrete implementations. Tier 2 (committed migration target)
— Rust adapters pending per RFC-006.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

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
                fragment_dir="queue_port/python",
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
                fragment_dir="queue_redis/python",
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
                fragment_dir="queue_sqs/python",
                dependencies=("aioboto3>=13.2.0",),
                env_vars=(("AWS_REGION", "us-east-1"),),
            ),
        },
    )
)
