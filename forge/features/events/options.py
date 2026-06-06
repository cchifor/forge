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
            summary="CloudEvents bus — domain-event fanout between services (vendored).",
            description="""\
Selects the ``app.events.EventBus`` transport (vendored, self-contained).
``postgres_notify`` uses Postgres ``LISTEN/NOTIFY`` (the default
transport — one ``domain_events`` channel per database, no extra infra).
``memory`` is for tests and local dev (subscribers in the same process).
``none`` disables the feature.

Pairs with the transactional outbox (``events.outbox``) so producers
never lose events on subscriber downtime.

BACKENDS: python
DEPENDENCY: none (vendored; uses pydantic + sqlalchemy from the base)""",
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
``app.events.OutboxRelay`` background worker that polls the table and
publishes pending rows through the configured ``EventBus``. Producers
append rows to ``outbox`` in the same transaction as their domain
writes — no dual-write race, no lost events on subscriber downtime.

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
