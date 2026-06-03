"""Console — a Layer-3 app template that composes Layer-1/2 components into a
dashboard. The loader auto-registers its emitter fragment; children (StatCard)
are pulled in by the component resolver when Console is selected."""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001
    return None
