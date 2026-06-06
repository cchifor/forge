"""forge-core — vendored, framework-agnostic primitives for forge services.

The vendored surfaces so far:

* :mod:`forge_core.errors` — the generic application / repository / service
  exception hierarchy plus the RFC-7807 :class:`Error` wire model.
* :mod:`forge_core.persistence` — a generic async SQLAlchemy persistence
  layer (engine, unit of work, generic repository, mixins) with opt-in,
  generic tenant scoping.
* :mod:`forge_core.domain` — generic identity + auth-config primitives
  (:class:`~forge_core.domain.Account`, :class:`~forge_core.domain.User`,
  :class:`~forge_core.domain.AuthConfig`, and the per-request identity
  ``context`` ``ContextVar`` set).
* :mod:`forge_core.discovery` — a generic Eureka service-discovery wrapper
  (optional ``py-eureka-client`` dependency, imported lazily).

The package re-exports only the small, stable error surface at top level;
import the rest from the submodule (``from forge_core.persistence import
AsyncBaseRepository``, ``from forge_core.domain import Account``) rather than
relying on package-level re-export.
"""

from forge_core.errors import (
    ApplicationError,
    AuthRequiredError,
    DuplicateEntryError,
    Error,
    ForeignKeyViolationError,
    NotFoundError,
    PermissionDeniedError,
    RepositoryError,
    ServiceError,
    ValidationError,
)

__all__ = [
    "ApplicationError",
    "AuthRequiredError",
    "DuplicateEntryError",
    "Error",
    "ForeignKeyViolationError",
    "NotFoundError",
    "PermissionDeniedError",
    "RepositoryError",
    "ServiceError",
    "ValidationError",
]
