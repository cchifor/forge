"""Chat history persistence and file uploads."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.conversation import fragments, options

    options.register_all(api)
    fragments.register_all(api)
