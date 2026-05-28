"""Client for the Airlock sandbox orchestrator (weld-airlock)."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.airlock import fragments, options

    options.register_all(api)
    fragments.register_all(api)
