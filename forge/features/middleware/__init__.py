"""``middleware.*`` features — request-path cross-cutting concerns.

Covers correlation IDs, rate limiting, security headers, PII-redacting
log filters, and opt-in HTTP response caching.
"""

from __future__ import annotations

from forge.features.middleware import (  # noqa: F401, E402
    fragments,
    options,
)
