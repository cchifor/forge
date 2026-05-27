"""``reliability.*`` features — connection pools, circuit breakers."""
from __future__ import annotations
from forge.api import ForgeAPI

def register(api: ForgeAPI) -> None:
    from forge.features.reliability import options, fragments
    options.register_all(api)
    fragments.register_all(api)
