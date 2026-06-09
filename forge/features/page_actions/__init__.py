"""PageActionGroup — a Layer-1 pure-UI canvas component (page action toolbar).

A *component* feature: ``feature.toml`` declares ``[feature].layer = 1`` and the
loader auto-registers the emitter fragment (``component_PageActionGroup``) from
the manifest, copying this feature's
``templates/component_PageActionGroup/all/files`` tree into the generated Vue
app. The feature declares no options/fragments of its own, so ``register`` is a
no-op.

The emitted component imports the base-template ``button`` and ``dropdown-menu``
primitives (``@/shared/ui/button`` / ``@/shared/ui/dropdown-menu``), which are
always present in the Vue frontend template.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001 — no options/fragments to add
    return None
