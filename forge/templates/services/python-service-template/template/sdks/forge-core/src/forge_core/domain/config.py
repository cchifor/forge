"""The generic OIDC client configuration the security layer reads.

:class:`AuthConfig` is the framework-agnostic (pydantic-only) description of
*which* OpenID-Connect provider a service trusts and *as whom* it presents
itself: the issuer base URL, the realm, the client credentials and the
expected token audience. The standard authorization-code-flow endpoint URLs
(:attr:`auth_url`, :attr:`token_url`) are *derived* from ``server_url`` +
``realm`` following the conventional OIDC discovery layout, so a service only
configures the few inputs and the rest follows.

This is the *generic* OIDC shape — issuer / realm / client / audience — and
not tied to any one provider or gateway product. A project that targets a
provider with a non-standard endpoint layout overrides :attr:`auth_url` /
:attr:`token_url` by subclassing, or supplies an explicit discovery document
in its own configuration; the defaults here cover the common Keycloak-style
``<server_url>/realms/<realm>/protocol/openid-connect/...`` convention.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthConfig(BaseModel):
    """OIDC client configuration for the service's security layer."""

    enabled: bool = Field(True, description="Enable authentication.")
    server_url: str = Field(
        ...,
        description=(
            "Trusted OIDC issuer base URL (e.g. http://localhost:8080). The "
            "realm-scoped authorization / token endpoints are derived from "
            "this and ``realm``."
        ),
    )
    realm: str = Field(
        default="master",
        description="OIDC realm the client authenticates against.",
    )
    client_id: str = Field(
        ...,
        description="The OIDC client id this service presents.",
    )
    client_secret: str | None = Field(
        default=None,
        description=(
            "The OIDC client secret for confidential clients. Required in "
            "production when ``enabled`` is true; ``None`` for public clients."
        ),
    )
    audience: str = Field(
        default="service-api",
        description="Expected ``aud`` claim on incoming bearer tokens.",
    )

    @property
    def _realm_base(self) -> str:
        """``<server_url>/realms/<realm>`` with no trailing slash."""
        base = self.server_url.rstrip("/")
        return f"{base}/realms/{self.realm}"

    @property
    def auth_url(self) -> str:
        """The OIDC authorization-code flow authorization endpoint."""
        return f"{self._realm_base}/protocol/openid-connect/auth"

    @property
    def token_url(self) -> str:
        """The OIDC authorization-code flow token endpoint."""
        return f"{self._realm_base}/protocol/openid-connect/token"
