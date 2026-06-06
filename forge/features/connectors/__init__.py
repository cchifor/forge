"""Pluggable read/write adapters (vendored, self-contained)."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.connectors import fragments, options

    options.register_all(api)
    fragments.register_all(api)
