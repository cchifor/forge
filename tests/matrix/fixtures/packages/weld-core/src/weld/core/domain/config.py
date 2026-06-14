"""``weld.core.domain.config.AuthConfig`` (matrix-CI stub).

Pydantic BaseModel — used as a sub-model of the template's
``SecurityConfig``. Field set is the union of what the template's
YAML config writes (``server_url``, ``realm``, ``client_id``,
``client_secret``, ``enabled``, ``audience``) and what the lifecycle
code reads (``auth_url``, ``token_url``, ``jwks_uri``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Loaded from YAML
    enabled: bool = False
    server_url: str = ""
    realm: str = ""
    client_id: str = ""
    client_secret: str = ""
    audience: str = ""
    issuer: str = ""
    tenant_id_claim: str = "https://forge/tenant_id"
    # Read by app/core/lifecycle.py — usually derived from server_url + realm
    auth_url: str = ""
    token_url: str = ""
    jwks_uri: str | None = None
