"""CloudEvents fragments — bus + transactional outbox via weld-events.

``events_core`` ships the bus factory and DI wiring so handlers can
publish ``CloudEvent`` instances directly. ``events_outbox`` layers on
the durable producer side (outbox table + relay loop) so events survive
listener downtime.

Both fragments are Python-only — weld-events has no Node/Rust
equivalent, and CloudEvent fanout in those ecosystems would be
implemented via a different library entirely.
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
        name="events_core",
        capabilities=("postgres",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("events_core", "python"),
                dependencies=("weld-events",),
                env_vars=(
                    ("EVENTS_BUS", "postgres_notify"),
                    ("EVENTS_CHANNEL", "domain_events"),
                ),
                reads_options=("events.bus",),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="events_outbox",
        depends_on=("events_core",),
        capabilities=("postgres",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("events_outbox", "python"),
                dependencies=("weld-events",),
                env_vars=(("EVENTS_OUTBOX_POLL_INTERVAL_S", "1.0"),),
            ),
        },
    )
)
