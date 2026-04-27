"""Fragment registry — see ``_spec.py`` and ``_registry.py``.

Importing this package triggers every per-namespace module's
``register_fragment`` calls, so ``FRAGMENT_REGISTRY`` is fully
populated by the time any caller does ``from forge.fragments import
FRAGMENT_REGISTRY``.

The package layout mirrors ``forge/options/``: one module per
capability namespace. Plugin authors should look at any of the
namespace modules (e.g. ``middleware.py``, ``rag.py``) for a concrete
example of registering fragments — the patterns there match what
``ForgeAPI.add_fragment`` consumes.
"""

from __future__ import annotations

# Trigger registrations. Order matters only for parity-tier auto-derivation
# of fragments whose ``depends_on`` cross-references; the registry's
# freeze-time audit catches any cycles or orphans regardless of import order.
from forge.fragments import (  # noqa: F401, E402
    agent,
    async_work,
    llm,
    middleware,
    object_store,
    observability,
    platform,
    queue,
    rag,
    reliability,
    security,
    vector_store,
)
from forge.fragments._registry import (
    FRAGMENT_REGISTRY,
    _FragmentRegistry,
    fragments_root,
    register_fragment,
)
from forge.fragments._spec import (
    FRAGMENTS_DIRNAME,
    MARKER_PREFIX,
    Fragment,
    FragmentImplSpec,
    FragmentScope,
    ParityTier,
)

__all__ = [
    "FRAGMENT_REGISTRY",
    "FRAGMENTS_DIRNAME",
    "Fragment",
    "FragmentImplSpec",
    "FragmentScope",
    "MARKER_PREFIX",
    "ParityTier",
    "_FragmentRegistry",
    "fragments_root",
    "register_fragment",
]
