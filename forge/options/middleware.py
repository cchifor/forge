"""``middleware.*`` options — request-path middleware on the backend.

Covers correlation IDs, rate limiting, security headers, PII-redacting
log filters, and opt-in HTTP response caching. Every option here is a
backend-only concern; the resolver expands the realising fragment per
target backend (Python / Node / Rust) where that backend supports it.
"""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="middleware.rate_limit",
        type=OptionType.BOOL,
        default=True,
        summary="Token-bucket limiter keyed by tenant or IP.",
        description="""\
Token-bucket rate limiter, keyed by tenant when authenticated or by
client IP otherwise. Protects downstream services from hot callers and
smooths burst traffic. Ships three first-class implementations with
matching knobs — Python (in-memory), Node (@fastify/rate-limit), Rust
(Axum tower layer).

BACKENDS: python, node, rust
ENDPOINTS: returns 429 on limit breach; /health and /metrics skipped.
REQUIRES: nothing by default; set REDIS_URL to share state across replicas.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("rate_limit",)},
    )
)


register_option(
    Option(
        path="middleware.security_headers",
        type=OptionType.BOOL,
        default=True,
        summary="CSP + XFO + HSTS + Referrer-Policy + Permissions-Policy.",
        description="""\
Attaches a conservative set of response headers (CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy, and HSTS
on HTTPS responses) to every request. Turning this off is a deliberate
choice for intentionally-insecure demos.

BACKENDS: python, node, rust
ENDPOINTS: none — middleware decorates every response.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("security_headers",)},
    )
)


register_option(
    Option(
        path="middleware.pii_redaction",
        type=OptionType.BOOL,
        default=True,
        summary="Logging filter that scrubs emails / tokens / API keys.",
        description="""\
A logging.Filter attached at startup that scrubs emails, bearer tokens,
common API-key shapes (sk-*, sk-ant-*, AIza*, hf_*), and
password=/api_key= value pairs from every log record before handlers
run. Helps satisfy GDPR / SOC2 log-hygiene requirements without
per-call-site discipline.

BACKENDS: python
ENDPOINTS: none — applies to logger output globally.""",
        category=FeatureCategory.RELIABILITY,
        enables={True: ("pii_redaction",)},
    )
)


register_option(
    Option(
        path="middleware.response_cache",
        type=OptionType.BOOL,
        default=False,
        summary="Opt-in HTTP response caching (Redis or in-memory).",
        description="""\
Wires a cache backend at startup so route handlers can decorate
themselves for server-side response caching. Python uses fastapi-cache2
with a Redis backend (falls back to in-memory if RESPONSE_CACHE_URL
isn't set); Node uses @fastify/caching. No blanket behavior change —
handlers opt in per-endpoint.

BACKENDS: python, node
ENDPOINTS: none — decorate existing routes with @cache(expire=N).
REQUIRES: RESPONSE_CACHE_URL pointing at Redis (recommended for prod).""",
        category=FeatureCategory.RELIABILITY,
        stability="beta",
        enables={True: ("response_cache",)},
    )
)
