"""Built-in forge feature modules.

Each subpackage colocates one feature's option(s), fragment(s), and
template tree under a single root, mirroring the layout that
third-party plugins use under the ``forge.plugins`` entry-point group
(see ``examples/forge-plugin-example/``). A contributor migrating a
feature out to a standalone plugin needs mostly a directory move plus
a ``pyproject.toml``.

Importing this package triggers each subpackage's
``register_option()`` / ``register_fragment()`` calls, populating
``OPTION_REGISTRY`` and ``FRAGMENT_REGISTRY``. Order does not matter —
the registry's freeze-time audit catches orphan ``depends_on`` and
cycles regardless of feature import order.

Depends on ``forge.options`` and ``forge.fragments`` being
import-complete first; ``forge/__init__.py`` enforces that ordering.
"""

from __future__ import annotations

from forge.features import (  # noqa: F401, E402
    agent,
    async_work,
    conversation,
    middleware,
    object_store,
    observability,
    platform,
    rag,
    reliability,
    security,
)
