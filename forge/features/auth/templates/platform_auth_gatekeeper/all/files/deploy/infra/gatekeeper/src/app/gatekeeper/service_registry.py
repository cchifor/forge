# src/app/gatekeeper/service_registry.py
"""Service-to-service client registry for the gatekeeper /auth/token endpoint.

The registry is loaded from a YAML file at gatekeeper startup and pinned on
``app.state.service_registry``. Each entry describes one service caller —
``svc-workflow``, ``svc-deepagent``, etc. — and the audiences it may mint
tokens for.

Schema example::

    services:
      - client_id: svc-workflow
        secret_hash: "$argon2id$v=19$m=65536,t=3,p=4$..."
        k8s_subject: "system:serviceaccount:platform:workflow"
        audiences:
          svc-knowledge:
            scopes: [knowledge:read]
          svc-mcp:
            scopes: [mcp:read, mcp:write]
        may_act_for_audiences: [svc-knowledge, svc-mcp]

``audiences`` keys define the per-(client, audience) allowed-scope set; the
``/auth/token`` endpoint intersects requested scopes with this set, never
exceeding it. ``may_act_for_audiences`` whitelists the audiences for which
the client may present a ``subject_token`` (RFC 8693 token-exchange).

Authorization decisions are pure functions of the registry — secret material
verification lives in :mod:`app.gatekeeper.service_verifier`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class AudienceConfig(BaseModel):
    """Per-audience scope grant for a single service client."""

    model_config = ConfigDict(extra="forbid")

    scopes: list[str] = Field(default_factory=list)


class ServiceClient(BaseModel):
    """One service caller's registry entry."""

    model_config = ConfigDict(extra="forbid")

    client_id: str
    secret_hash: str | None = None
    """argon2id hash of the pre-shared secret. Required when the
    ``preshared`` verifier is configured; ignored otherwise."""
    k8s_subject: str | None = None
    """``system:serviceaccount:<ns>:<name>`` mapping for the
    :class:`ProjectedSATokenVerifier`. Ignored otherwise."""
    mtls_subject: str | None = None
    """Cert distinguished-name for the :class:`MtlsVerifier`. Format
    matches what the reverse proxy forwards on ``X-SSL-Client-S-DN``
    (typically ``CN=svc-name,O=...,C=...``). Ignored otherwise."""
    audiences: dict[str, AudienceConfig] = Field(default_factory=dict)
    may_act_for_audiences: list[str] = Field(default_factory=list)

    @field_validator("client_id")
    @classmethod
    def _require_svc_prefix(cls, value: str) -> str:
        """Enforce the ``svc-`` prefix on every service ``client_id``.

        Client-credentials mints set ``azp = client_id``, and the
        token-exchange guard in :mod:`app.gatekeeper.service_token` rejects
        service-account ``subject_token``s via ``azp.startswith("svc-")``.
        That guard is only sound if every registered service client carries
        the prefix, so we reject unprefixed ids at model-validation time
        rather than letting a hand-edited registry silently defeat it.
        """
        if not value.startswith("svc-"):
            raise ValueError(
                f"service client_id must start with 'svc-'; got {value!r}"
            )
        return value

    def allowed_scopes_for(self, audience: str) -> frozenset[str]:
        """Return the registry-allowed scope set for ``audience`` or empty."""
        cfg = self.audiences.get(audience)
        return frozenset(cfg.scopes) if cfg is not None else frozenset()

    def may_act_for(self, audience: str) -> bool:
        """Whether this client is allowed to mint via token-exchange for ``audience``."""
        return audience in self.may_act_for_audiences


class ServiceRegistry(BaseModel):
    """Top-level YAML schema."""

    model_config = ConfigDict(extra="forbid")

    services: list[ServiceClient] = Field(default_factory=list)

    def lookup(self, client_id: str) -> ServiceClient | None:
        """Return the registry entry for ``client_id`` or ``None``."""
        for entry in self.services:
            if entry.client_id == client_id:
                return entry
        return None

    @property
    def client_ids(self) -> frozenset[str]:
        return frozenset(s.client_id for s in self.services)


class RegistryError(RuntimeError):
    """Raised when the registry file is missing, malformed, or empty."""


def load_registry(path: Path) -> ServiceRegistry:
    """Read and validate the registry YAML at ``path``.

    Raises :class:`RegistryError` if the file is missing, unreadable, or
    fails schema validation. A registry with zero services is allowed —
    gatekeeper still serves user traffic; only ``/auth/token`` becomes
    unusable, which fails closed at the endpoint level.

    The same client_id appearing twice is rejected: ambiguous mapping is
    a config bug we want to surface at boot, not on first request.
    """
    if not path.is_file():
        raise RegistryError(f"service registry file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegistryError(f"service registry YAML parse failed: {exc}") from exc

    if raw is None:
        raw = {"services": []}

    try:
        registry = ServiceRegistry.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError → message preservation
        raise RegistryError(f"service registry schema invalid: {exc}") from exc

    seen: set[str] = set()
    for entry in registry.services:
        if entry.client_id in seen:
            raise RegistryError(
                f"service registry has duplicate client_id={entry.client_id!r}"
            )
        seen.add(entry.client_id)

    logger.info(
        "service_registry loaded path=%s clients=%d",
        path,
        len(registry.services),
    )
    return registry


__all__ = [
    "AudienceConfig",
    "RegistryError",
    "ServiceClient",
    "ServiceRegistry",
    "load_registry",
]
