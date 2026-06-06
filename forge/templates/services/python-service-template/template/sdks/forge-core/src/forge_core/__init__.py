"""forge-core — vendored, framework-agnostic primitives for forge services.

The first vendored surface is the generic error contract: an application /
repository / service exception hierarchy plus the RFC-7807 :class:`Error`
wire model. Subsequent blocks add persistence, domain and discovery
primitives under their own submodules.

The public surface is intentionally small; import from the submodule
(``from forge_core.errors import Error``) rather than relying on this
package re-exporting everything.
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
