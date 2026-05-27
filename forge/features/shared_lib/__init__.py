"""Shared library scaffold — cross-backend code sharing."""
from __future__ import annotations
from forge.api import ForgeAPI

def register(api: ForgeAPI) -> None:
    from forge.features.shared_lib import options, fragments
    options.register_all(api)
    fragments.register_all(api)
