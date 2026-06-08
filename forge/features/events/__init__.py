"""CloudEvents bus and transactional outbox (vendored, self-contained)."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.events import fragments, options

    options.register_all(api)
    fragments.register_all(api)
