"""``object_store.*`` features — blob storage port + adapters."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.object_store import fragments, options

    options.register_all(api)
    fragments.register_all(api)
