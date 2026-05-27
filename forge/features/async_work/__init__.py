"""Off-thread job processing via Redis-backed queues."""
from __future__ import annotations
from forge.api import ForgeAPI

def register(api: ForgeAPI) -> None:
    from forge.features.async_work import options, fragments
    options.register_all(api)
    fragments.register_all(api)
