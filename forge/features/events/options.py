"""``events.*`` — CloudEvents bus + transactional outbox options."""

from __future__ import annotations

from forge.api import ForgeAPI
from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
)


def register_all(api: ForgeAPI) -> None:
    api.add_option(
        Option(
            path="events.bus",
            type=OptionType.ENUM,
            default="none",
            options=("none", "postgres_notify", "memory"),
            summary="CloudEvents bus — domain-event fanout between services (weld-events).",
            description="""\
Selects the :class:`weld.events.EventBus` transport. ``postgres_notify``
uses Postgres ``LISTEN/NOTIFY`` (the default platform transport — one
``domain_events`` channel per database, no extra infra). ``memory`` is
for tests and local dev (subscribers in the same process). ``none``
disables the feature.

Pairs with the transactional outbox (``events.outbox``) so producers
never lose events on listener downtime.

BACKENDS: python
DEPENDENCY: weld-events""",
            category=FeatureCategory.ASYNC_WORK,
            # Initiative #7 — only the values that resolve to fragments are
            # checked. ``postgres_notify`` and ``memory`` both need a DB
            # because ``events_core`` ships an alembic migration. ``none``
            # has no enables → is_active_value returns False → no DB check.
            requires_database=True,
            enables={
                "postgres_notify": ("events_core",),
                "memory": ("events_core",),
            },
        )
    )

    api.add_option(
        Option(
            path="events.outbox",
            type=OptionType.BOOL,
            default=False,
            summary="Transactional outbox table — never-lost CloudEvents on the producer side.",
            description="""\
Adds the ``outbox`` table (via Alembic migration) and an
:class:`weld.events.OutboxRelay` background worker that polls the
table and publishes pending rows through the configured ``EventBus``.
Producers append rows to ``outbox`` in the same transaction as their
domain writes — no dual-write race, no lost events on listener
downtime.

Default is off because turning the outbox on without ``events.bus``
configured would pull in the bus + relay scaffolding for a service
that never publishes. Enable both together when adopting the bus.

REQUIRES: ``events.bus`` ≠ ``none``.
BACKENDS: python""",
            category=FeatureCategory.ASYNC_WORK,
            # Initiative #7 — outbox is a DB table with its own alembic
            # migration; can't exist without a database.
            requires_database=True,
            enables={True: ("events_outbox",)},
        )
    )
