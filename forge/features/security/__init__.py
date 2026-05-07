"""``security.*`` features — CSP nginx config + SBOM workflow.

Distinct from ``middleware.security_headers`` (which is in
``forge.features.middleware`` and sets HTTP response headers in the
request path); these fragments are project-scope (``security_csp``
ships an external CSP config) or build-time (``security_sbom`` emits
a software-bill-of-materials artifact).
"""

from __future__ import annotations

from forge.features.security import (  # noqa: F401, E402
    fragments,
    options,
)
