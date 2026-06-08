"""AsyncStateBlock — a Layer-1 pure-UI component (async-state orchestrator).

A *component* feature: ``feature.toml`` declares ``[feature].layer = 1`` and the
loader auto-registers the emitter fragment (``component_AsyncStateBlock``) from
the manifest, copying this feature's ``templates/component_AsyncStateBlock/all/
files`` tree into the generated Vue app. It ships two sibling components —
``AsyncStateBlock`` (the loading→error→empty→success ladder) and the
``FeatureEmptyState`` it renders for the empty/error branches. The feature
declares no options/fragments of its own, so ``register`` is a no-op.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001 — no options/fragments to add
    return None
