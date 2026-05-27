"""Pluggable read/write adapters via weld-connectors."""
from __future__ import annotations
from forge.api import ForgeAPI

def register(api: ForgeAPI) -> None:
    from forge.features.connectors import options, fragments
    options.register_all(api)
    fragments.register_all(api)
