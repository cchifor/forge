"""EntityList — a Layer-1 data-bound canvas component.

A *component* feature: ``feature.toml`` declares ``[feature].layer = 1`` and a
``[feature.component].contract`` reference. The loader auto-registers the emitter
fragment (``component_EntityList``) from the manifest, copying this feature's
``templates/component_EntityList/all/files`` tree into the generated Vue app. The
contract lives feature-local (``EntityList.contract.json``) so it never flips the
shared canvas manifest to v2; ``run_codegen`` emits ``EntityList.contract.ts``
(op input/output interfaces) into ``shared/api`` and the ``.vue`` imports it so a
contract change is caught at build time by ``vue-tsc`` (plan §D). The feature
declares no options/fragments of its own, so ``register`` is a no-op.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001 — no options/fragments to add
    return None
