"""Module-level adapter container for fragment-injected wiring.

Forge fragments (LLM, vector-store, queue, object-store) inject their
adapter instantiation snippets after the ``FORGE:APP_POST_CONFIGURE``
marker below. The instances are intentionally module-level so they
construct exactly once at import time and stay accessible to handlers
without going through FastAPI's per-request dependency-resolution
machinery.

When no fragments inject, this file is empty save for the marker — that
is fine. ``main.py`` imports it for side effects only:

    from app.core import container as _container  # noqa: F401
"""

# FORGE:APP_POST_CONFIGURE
