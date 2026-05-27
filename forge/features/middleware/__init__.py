"""``middleware.*`` features — request-path cross-cutting concerns."""
from __future__ import annotations
from forge.api import ForgeAPI

def register(api: ForgeAPI) -> None:
    from forge.features.middleware import options, fragments
    options.register_all(api)
    fragments.register_all(api)
