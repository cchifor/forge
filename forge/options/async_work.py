"""``async.*`` and ``queue.*`` — off-thread job processing."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="async.task_queue",
        type=OptionType.BOOL,
        default=False,
        summary="Redis-backed job queue (Taskiq / BullMQ / Apalis).",
        description="""\
A Redis-backed job queue + example task + worker binary. Define jobs as
regular async functions, enqueue them from request handlers, process
them out-of-process in a dedicated worker container. Ships with Taskiq
(Python), BullMQ + ioredis (Node), and Apalis (Rust) — three different
ecosystems with the same env-var convention (TASKIQ_BROKER_URL).

BACKENDS: python, node, rust
REQUIRES: TASKIQ_BROKER_URL → Redis.""",
        category=FeatureCategory.ASYNC_WORK,
        stability="beta",
        enables={True: ("background_tasks",)},
    )
)


register_option(
    Option(
        path="async.rag_ingest_queue",
        type=OptionType.BOOL,
        default=False,
        summary="Taskiq tasks that move RAG ingest off the request thread.",
        description="""\
Taskiq tasks that move RAG ingestion off the request thread. Enqueue
with ``await ingest_text_task.kiq(...)`` or
``ingest_pdf_bytes_task.kiq(...)`` from any handler — the worker picks
it up and runs chunk + embed + store in the background. The endpoint
returns immediately with a task ID.

BACKENDS: python
REQUIRES: rag.backend ≠ none + async.task_queue = true.""",
        category=FeatureCategory.ASYNC_WORK,
        stability="experimental",
        enables={True: ("rag_sync_tasks",)},
    )
)


register_option(
    Option(
        path="queue.backend",
        type=OptionType.ENUM,
        default="none",
        options=("none", "redis", "sqs"),
        summary="Background-work queue — Redis lists or AWS SQS, behind the QueuePort.",
        description="""\
Selects which queue implementation the ``QueuePort`` resolves to.
Redis is the simple-and-cheap default for self-hosted setups; SQS
covers AWS-native deployments with delayed delivery + FIFO.

OPTIONS: none | redis | sqs
BACKENDS: python
DEPENDENCY: redis-py (redis) or aioboto3 (sqs)
ENV: REDIS_URL / AWS_REGION""",
        category=FeatureCategory.ASYNC_WORK,
        enables={
            "redis": ("queue_port", "queue_redis"),
            "sqs": ("queue_port", "queue_sqs"),
        },
    )
)
