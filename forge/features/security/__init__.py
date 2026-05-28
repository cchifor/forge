"""CSP nginx config + SBOM workflow."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.security import fragments, options

    options.register_all(api)
    fragments.register_all(api)
