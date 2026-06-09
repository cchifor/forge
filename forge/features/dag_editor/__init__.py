"""DagEditor component-feature.

A generic node/edge DAG editor: a Vue Flow canvas with dagre auto-layout,
extracted (de-coupled from any workflow/domain model) into a reusable Layer-1
component. Opt-in via ``ProjectConfig.components=["DagEditor"]``; auto-compiled
from ``feature.toml`` by the feature loader, so ``register`` is a no-op.

Its npm deps (``@vue-flow/*`` + ``dagre``) are gated in the Vue template's
``package.json.jinja`` on the ``include_dag_editor`` flag (set by
``variable_mapper.vue_context`` when this component is selected), so projects
that don't use it — and every golden snapshot — stay byte-identical.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001 — auto-discovered component
    """No-op: the component is compiled from ``feature.toml`` by the loader."""
