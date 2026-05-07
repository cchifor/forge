"""``middleware.*`` features — request-path cross-cutting concerns.

POC scope (Step 2 of the features-reorganization refactor): this
subpackage owns ``correlation_id`` only. The remaining middleware
fragments (``rate_limit``, ``security_headers``, ``pii_redaction``,
``response_cache``) still register from ``forge/options/middleware.py``
and ``forge/fragments/middleware.py``; they migrate in Wave A once the
POC validates path resolution and import ordering.
"""

from __future__ import annotations

from forge.features.middleware import (  # noqa: F401, E402
    fragments,
    options,
)
