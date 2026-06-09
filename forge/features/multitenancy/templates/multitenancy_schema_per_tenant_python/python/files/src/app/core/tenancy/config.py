"""Configuration for tenant isolation (schema_per_tenant).

Two sources, by code path:

- The **request path** uses ``app.state.tenancy_settings``, which the generator
  bakes from the project's forge.toml choice (see the ``FORGE:APP_POST_CONFIGURE``
  injection in this fragment's ``inject.yaml``). That is authoritative for
  served requests — the forge-time ``database.tenant_resolution`` /
  ``tenant_claim_path`` / ``tenant_header_name`` selection wins and is NOT
  re-read from the environment per request.
- **Out-of-band code** (workers / CLI / the imperative ``TenantSchemaHook``)
  that has no ``app.state`` calls :func:`get_tenancy_settings`, which reads the
  environment once (lru-cached) with the defaults below.

==========================  ==================================  ================
Env var                     Meaning                             Default
==========================  ==================================  ================
``TENANT_RESOLUTION``       token_claim | header | subdomain    ``token_claim``
``TENANT_CLAIM_PATH``       dot-path to the tenant id in the    ``tenant_id``
                            verified token claims.
``TENANT_HEADER_NAME``      header carrying the tenant id.      ``X-Tenant-ID``
``TENANT_SCHEMA_PREFIX``    prefix prepended to the tenant id   ``tenant_``
                            to form the Postgres schema name.
==========================  ==================================  ================

``TENANT_SCHEMA_PREFIX`` is the one knob written to the generated ``.env`` (it
is a fragment ``env_var``); it ensures the derived schema name starts with a
letter (a bare numeric/UUID tenant id is not a legal leading identifier char).
The schema prefix has no forge option — it is fragment-local.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

VALID_STRATEGIES: frozenset[str] = frozenset({"token_claim", "header", "subdomain"})

DEFAULT_RESOLUTION = "token_claim"
DEFAULT_CLAIM_PATH = "tenant_id"
DEFAULT_HEADER_NAME = "X-Tenant-ID"
DEFAULT_SCHEMA_PREFIX = "tenant_"


class TenancyConfigError(ValueError):
    """Raised when the ``TENANT_*`` environment is invalid."""


@dataclass(slots=True, frozen=True)
class TenancySettings:
    """Resolved, validated tenant-resolution configuration."""

    resolution: str = DEFAULT_RESOLUTION
    claim_path: str = DEFAULT_CLAIM_PATH
    header_name: str = DEFAULT_HEADER_NAME
    schema_prefix: str = DEFAULT_SCHEMA_PREFIX

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
        # The prefix guarantees the schema name starts with a letter and is
        # itself a legal identifier head; reject anything outside [a-z0-9_].
        if not self.schema_prefix or not self.schema_prefix[0].isalpha():
            raise TenancyConfigError(
                "TENANT_SCHEMA_PREFIX must be non-empty and start with a letter"
            )
        if any(c not in _PREFIX_CHARS for c in self.schema_prefix.lower()):
            raise TenancyConfigError(
                "TENANT_SCHEMA_PREFIX must contain only [a-z0-9_]"
            )


# Lowercased character set allowed in the schema prefix.
_PREFIX_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def load_tenancy_settings(env: dict[str, str] | None = None) -> TenancySettings:
    """Build :class:`TenancySettings` from ``env`` (defaults to ``os.environ``)."""
    source = os.environ if env is None else env
    return TenancySettings(
        resolution=(source.get("TENANT_RESOLUTION") or DEFAULT_RESOLUTION).strip(),
        claim_path=(source.get("TENANT_CLAIM_PATH") or DEFAULT_CLAIM_PATH).strip(),
        header_name=(source.get("TENANT_HEADER_NAME") or DEFAULT_HEADER_NAME).strip(),
        schema_prefix=(source.get("TENANT_SCHEMA_PREFIX") or DEFAULT_SCHEMA_PREFIX).strip(),
    )


@lru_cache(maxsize=1)
def get_tenancy_settings() -> TenancySettings:
    """Process-wide cached tenancy settings (read from ``os.environ`` once)."""
    return load_tenancy_settings()


__all__ = [
    "DEFAULT_CLAIM_PATH",
    "DEFAULT_HEADER_NAME",
    "DEFAULT_RESOLUTION",
    "DEFAULT_SCHEMA_PREFIX",
    "VALID_STRATEGIES",
    "TenancyConfigError",
    "TenancySettings",
    "get_tenancy_settings",
    "load_tenancy_settings",
]
