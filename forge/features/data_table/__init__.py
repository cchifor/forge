"""DataTable — a Layer-1 pure-UI component feature (Vue).

A *component* feature: ``feature.toml`` declares ``[feature].layer = 1`` and the
loader auto-registers the emitter fragment (``component_DataTable``) from the
manifest, copying this feature's ``templates/component_DataTable/all/files`` tree
into the generated Vue app. It ships a TanStack-Table-backed data grid
(``DataTable.vue`` + ``useDataTable`` + the ``useColumnManager`` family of
visibility/order/pinning/sizing composables) plus the ``ColumnManagerMenu``
popover and the self-contained ``checkbox`` / ``popover`` primitives those
surfaces need — kept local to the feature so it never collides with the
NotificationCenter feature, which ships its own ``@/shared/ui/popover``.

Because ``.vue`` files cannot be sentinel-injected, consumers import
``{ DataTable, ColumnManagerMenu, useDataTable }`` from
``@/shared/ui/data-table`` themselves (documented in the feature README). The
feature declares no options/fragments of its own, so ``register`` is a no-op.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001 — no options/fragments to add
    return None
