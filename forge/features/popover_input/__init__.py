"""Popover — a Layer-1 pure-UI canvas component (radix-vue popover).

A *component* feature: ``feature.toml`` declares ``[feature].layer = 1`` and the
loader auto-registers the emitter fragment (``component_Popover``) from the
manifest, copying this feature's ``templates/component_Popover/all/files`` tree
into the generated Vue app. The feature declares no options/fragments of its
own, so ``register`` is a no-op.

The barrel re-exports the radix-vue ``PopoverRoot``/``Trigger``/``Anchor``/
``Close`` primitives directly and ships a styled ``PopoverContent`` wrapper
(portal + animations + popover-surface tokens).
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001 — no options/fragments to add
    return None
