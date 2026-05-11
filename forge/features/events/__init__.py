"""``events.*`` — CloudEvents bus + transactional outbox via weld-events.

CloudEvents-shaped inter-service messaging on top of the platform's
``weld-events`` SDK. The default transport is Postgres ``LISTEN/NOTIFY``
behind :class:`weld.events.PostgresNotifyBus`; the bus is pluggable via
the :class:`weld.events.EventBus` Protocol so a future Kafka or NATS
implementation slots in without touching call sites.

Distinct from ``async.*`` (Taskiq/BullMQ/Apalis intra-service job
queues): events here are domain CloudEvents fanned out *between*
services. Both can coexist — services emit CloudEvents for cross-team
consumption and use task queues for off-thread compute.

Pairs with ``forge.features.streaming`` (weld-streaming) when a service
needs to fan CloudEvents out to browser SSE subscribers — streaming
``depends_on`` ``events_core``.
"""

from __future__ import annotations

from forge.features.events import (  # noqa: F401, E402
    fragments,
    options,
)
