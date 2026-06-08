"""forge-core domain — the generic identity + auth-config primitives.

A small, framework-agnostic (stdlib + pydantic only) set of building
blocks a generated service builds its request-context and auth wiring on:

* :class:`Account` / :class:`UserRole` — the per-request caller-identity
  holder the persistence layer scopes against (it satisfies
  :class:`forge_core.persistence.AccountProtocol`).
* :class:`User` — the authenticated-principal model an auth layer hydrates
  from a verified token and a service injects into request handlers.
* :class:`AuthConfig` — the generic OIDC client configuration (issuer /
  realm / client credentials / audience) the security layer reads, with the
  standard authorization-code endpoint URLs derived as properties.
* :mod:`forge_core.domain.context` — the per-request identity ``ContextVar``
  set, importable as ``from forge_core.domain import context``.

This package is deliberately *generic*: it carries the identity fields every
service needs (ids, tenant binding, email/name, roles) and none of any one
product's governance specifics. Product-specific identity (platform-admin
flags, a fixed service-scope graph, tenant-suspension state) belongs in the
generating project, not here.
"""

from forge_core.domain import context
from forge_core.domain.account import Account, UserRole
from forge_core.domain.config import AuthConfig
from forge_core.domain.user import User

__all__ = [
    "Account",
    "AuthConfig",
    "User",
    "UserRole",
    "context",
]
