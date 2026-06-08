"""NotificationCenter — a Layer-2 pure-UI component feature (Vue).

A *component* feature: ``feature.toml`` declares ``[feature].layer = 2`` and the
loader auto-registers the emitter fragment (``component_NotificationCenter``)
from the manifest, copying this feature's ``templates/component_NotificationCenter/
all/files`` tree into the generated Vue app. It ships the notifications feature
module (Pinia store + SSE stream consumer built on ``useEventStream`` + toast
shim + REST client + cache-invalidation registry) plus the bell / center /
connection-banner / toast-host components and the supporting ``Popover`` UI,
``RelativeTime`` component, and ``formatTime`` util it depends on.

Because ``.vue`` files cannot be sentinel-injected, the four one-time wiring
edits (bell into the header, ToastHost into the app root, the route bootstrap)
are documented in the feature README rather than auto-applied — same pattern as
the session-timeout fragment. The feature declares no options/fragments of its
own, so ``register`` is a no-op.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:  # noqa: ARG001 — no options/fragments to add
    return None
