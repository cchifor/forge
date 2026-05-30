"""Enhanced testing infrastructure — failure forensics + coverage registry."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.testing_enhanced import fragments, options

    options.register_all(api)
    fragments.register_all(api)
