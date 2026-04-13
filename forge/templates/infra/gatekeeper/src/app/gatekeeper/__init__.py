# src/app/gatekeeper/__init__.py
"""
Gatekeeper — OIDC Relying Party & Traefik ForwardAuth middleware.

Submodules:
- config:      Environment-based settings (GatekeeperSettings).
- jwks:        Cached JWKS fetching and JWT validation.
- oidc:        Token exchange and refresh helpers.
- routes:      FastAPI endpoints (/auth, /callback, /logout, /metrics).
- redis:       Async Redis connection pool management.
- apikeys:     API key generation, hashing, and Redis-backed validation.
- apikeys_api: REST API for API key lifecycle (create, list, revoke).
- ratelimit:   Distributed tenant-level rate limiting via Redis.
- metrics:     Prometheus counters and histograms for observability.
"""
