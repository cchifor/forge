"""Switch — a Layer-1 pure-UI canvas component (toggle switch).

A *component* feature: ``feature.toml`` declares ``[feature].layer = 1`` and the
loader auto-registers the emitter fragment (``component_Switch``) from the
manifest, copying this feature's ``templates/component_Switch/all/files`` tree
into the generated Vue app. The feature declares no options/fragments of its
own, so ``register`` is a no-op.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001 — no options/fragments to add
    return None
