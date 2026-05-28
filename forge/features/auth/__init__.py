"""Identity, RBAC, and S2S authentication primitives."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.auth import fragments, options

    options.register_all(api)
    fragments.register_all(api)
