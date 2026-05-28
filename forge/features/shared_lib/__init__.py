"""Shared library scaffold — cross-backend code sharing."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.shared_lib import fragments, options

    options.register_all(api)
    fragments.register_all(api)
