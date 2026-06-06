"""CloudEvents fragments — bus + transactional outbox (vendored, weld-free).

``events_core`` ships a self-contained CloudEvents envelope, the
:class:`EventBus` protocol (with Postgres ``LISTEN/NOTIFY`` + in-memory
transports), the bus factory, and DI wiring so handlers can publish
``CloudEvent`` instances directly. ``events_outbox`` layers on the
durable producer side (outbox table + relay loop) so events survive
subscriber downtime.

The mechanism is vendored into each generated project (``src/app/events/``)
and imports only the stdlib + pydantic + sqlalchemy — no private SDKs.
Optional CloudEvent extensions (tenant / actor) are nullable, so a
single-tenant service stays lean.

Both fragments are Python-only — CloudEvent fanout in Node/Rust would be
implemented via a different library entirely.
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
            name="events_core",
            capabilities=("postgres",),
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("events_core", "python"),
                    # No extra deps: the vendored bus needs only pydantic
                    # + sqlalchemy, both base-template dependencies.
                    env_vars=(
                        ("EVENTS_BUS", "postgres_notify"),
                        ("EVENTS_CHANNEL", "domain_events"),
                    ),
                    reads_options=("events.bus",),
                ),
            },
        )
    )

    api.add_fragment(
        Fragment(
            name="events_outbox",
            depends_on=("events_core",),
            capabilities=("postgres",),
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("events_outbox", "python"),
                    # No extra deps: the vendored outbox store + relay use
                    # only sqlalchemy, a base-template dependency.
                    env_vars=(("EVENTS_OUTBOX_POLL_INTERVAL_S", "1.0"),),
                ),
            },
        )
    )
