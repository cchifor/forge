"""SSE fanout of CloudEvents to browser subscribers (vendored, self-contained)."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.streaming import fragments, options

    options.register_all(api)
    fragments.register_all(api)
