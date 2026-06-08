"""Env-driven configuration for tenant isolation (shared_rls).

Resolved once at import via :func:`get_tenancy_settings` (lru-cached). All
knobs map to the ``database.*`` forge options that selected this fragment, but
are read from the environment at runtime so a deployment can override the
resolution strategy without a re-generate:

==========================  ==================================  ================
Env var                     Meaning                             Default
==========================  ==================================  ================
``TENANT_RESOLUTION``       token_claim | header | subdomain    ``token_claim``
``TENANT_CLAIM_PATH``       dot-path to the tenant id in the    ``tenant_id``
                            verified token claims.
``TENANT_HEADER_NAME``      header carrying the tenant id.      ``X-Tenant-ID``
``TENANT_RLS_GUC``          Postgres GUC the tenant id binds    ``app.current_tenant``
                            to (must match the RLS migration).
==========================  ==================================  ================

The defaults match the forge option defaults (``database.tenant_resolution``
etc.); the generated ``.env.example`` records the project's chosen values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

VALID_STRATEGIES: frozenset[str] = frozenset({"token_claim", "header", "subdomain"})

DEFAULT_RESOLUTION = "token_claim"
DEFAULT_CLAIM_PATH = "tenant_id"
DEFAULT_HEADER_NAME = "X-Tenant-ID"
DEFAULT_GUC = "app.current_tenant"


class TenancyConfigError(ValueError):
    """Raised when the ``TENANT_*`` environment is invalid."""


@dataclass(slots=True, frozen=True)
class TenancySettings:
    """Resolved, validated tenant-resolution configuration."""

    resolution: str = DEFAULT_RESOLUTION
    claim_path: str = DEFAULT_CLAIM_PATH
    header_name: str = DEFAULT_HEADER_NAME
    guc: str = DEFAULT_GUC

    def __post_init__(self) -> None:
        if self.resolution not in VALID_STRATEGIES:
            valid = ", ".join(sorted(VALID_STRATEGIES))
            raise TenancyConfigError(
                f"TENANT_RESOLUTION={self.resolution!r} is invalid; valid: {valid}"
            )
        if not self.claim_path:
            raise TenancyConfigError("TENANT_CLAIM_PATH must be non-empty")
        if not self.header_name:
            raise TenancyConfigError("TENANT_HEADER_NAME must be non-empty")
        if not self.guc:
            raise TenancyConfigError("TENANT_RLS_GUC must be non-empty")


def load_tenancy_settings(env: dict[str, str] | None = None) -> TenancySettings:
    """Build :class:`TenancySettings` from ``env`` (defaults to ``os.environ``)."""
    source = os.environ if env is None else env
    return TenancySettings(
        resolution=(source.get("TENANT_RESOLUTION") or DEFAULT_RESOLUTION).strip(),
        claim_path=(source.get("TENANT_CLAIM_PATH") or DEFAULT_CLAIM_PATH).strip(),
        header_name=(source.get("TENANT_HEADER_NAME") or DEFAULT_HEADER_NAME).strip(),
        guc=(source.get("TENANT_RLS_GUC") or DEFAULT_GUC).strip(),
    )


@lru_cache(maxsize=1)
def get_tenancy_settings() -> TenancySettings:
    """Process-wide cached tenancy settings (read from ``os.environ`` once)."""
    return load_tenancy_settings()


__all__ = [
    "DEFAULT_CLAIM_PATH",
    "DEFAULT_GUC",
    "DEFAULT_HEADER_NAME",
    "DEFAULT_RESOLUTION",
    "VALID_STRATEGIES",
    "TenancyConfigError",
    "TenancySettings",
    "get_tenancy_settings",
    "load_tenancy_settings",
]
