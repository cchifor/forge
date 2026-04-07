# src/app/gatekeeper/config.py
"""
Gatekeeper configuration loaded entirely from environment variables.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class GatekeeperSettings(BaseSettings):
    """
    All configuration is read from environment variables.

    | Variable                  | Description                                  |
    |---------------------------|----------------------------------------------|
    | KEYCLOAK_BASE_URL         | Internal Keycloak address                    |
    | GATEKEEPER_CLIENT_ID      | OIDC client ID registered in Keycloak        |
    | GATEKEEPER_CLIENT_SECRET  | OIDC client secret                           |
    | COOKIE_NAME               | Name of the session cookie (access token)    |
    | COOKIE_SECURE             | Enforce HTTPS-only cookies (True in prod)    |
    | REFRESH_COOKIE_NAME       | Name of the refresh-token cookie             |
    | JWKS_CACHE_TTL            | JWKS cache TTL in seconds (default 900)      |
    | REDIS_URL                 | Redis connection URL                         |
    | DEFAULT_RATE_LIMIT        | Default requests-per-minute per tenant        |
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    keycloak_base_url: str = "http://keycloak:8080/realms"
    gatekeeper_client_id: str = "multi-tenant-gateway"
    gatekeeper_client_secret: str = "super-secret-string"
    cookie_name: str = "tenant_session"
    cookie_secure: bool = False
    refresh_cookie_name: str = "tenant_refresh"
    jwks_cache_ttl: int = 900  # 15 minutes

    # Redis
    redis_url: str = "redis://redis:6379"

    # Rate limiting
    default_rate_limit: int = 600  # requests per minute

    # Tenant config cache (dynamic resolution via TMS)
    tenant_config_cache_ttl: int = 60  # seconds

    # Internal test bypass (disabled by default, dev/test environments only)
    test_bypass_enabled: bool = False
    test_bypass_token: str = ""
    test_bypass_tenant_ids: str = ""  # Comma-separated allowed tenant IDs


# ── Lazy singleton ──────────────────────────────────────────────────────────

_instance: GatekeeperSettings | None = None


def get_settings() -> GatekeeperSettings:
    """Return (and cache) the singleton settings instance."""
    import logging as _log

    global _instance
    if _instance is None:
        _instance = GatekeeperSettings()
        # Validate test bypass configuration
        if _instance.test_bypass_enabled:
            if len(_instance.test_bypass_token) < 16:
                _log.getLogger(__name__).warning(
                    "TEST_BYPASS_TOKEN is too short (< 16 chars) — bypass may be insecure"
                )
            if not _instance.test_bypass_tenant_ids.strip():
                _log.getLogger(__name__).warning(
                    "TEST_BYPASS_TENANT_IDS is empty — bypass will reject all tenants"
                )
            _log.getLogger(__name__).warning(
                "Test bypass is ENABLED — ensure this is a non-production environment"
            )
    return _instance
