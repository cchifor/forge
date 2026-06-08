"""Generic application + repository error hierarchy and the RFC-7807 wire shape.

This module is the vendored, framework-agnostic error contract every
forge-generated service builds on. It deliberately keeps two concerns
side by side but decoupled:

* The **Python exception hierarchy** (:class:`ApplicationError` and its
  descendants) that service / repository code *raises*.
* The **JSON wire contract** (:class:`Error`) that an HTTP layer *returns*.

The two intentionally don't reference each other — a service typically
catches an :class:`ApplicationError` in an exception handler and translates
it into an :class:`Error` response body. Keeping the wire model free of the
exception tree means non-FastAPI transports (gRPC, CLI, workers) can reuse
the exception hierarchy without importing a pydantic model they don't need.

The hierarchy here is the *generic* subset: ``NotFound``, ``Conflict``
(duplicate / FK), ``Validation``, ``Unauthorized`` and ``Forbidden``
shapes that every service needs. Product-specific auth failures
(tenant-suspension, scope-required, issuer-trust, on-behalf-of actor
checks) deliberately live in the auth SDK, not here, so this stays a
transport- and product-neutral foundation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# --- Application error hierarchy ---------------------------------------------


class ApplicationError(Exception):
    """Base class for all application-specific errors."""

    @property
    def message(self) -> str:
        return self.args[0] if self.args else "An application error occurred."


# --- Repository & persistence errors ----------------------------------------


class RepositoryError(ApplicationError):
    """Base class for repository / persistence-layer errors."""


class NotFoundError(RepositoryError):
    """Raised when a requested entity does not exist."""

    def __init__(self, entity_name: str, entity_id: Any | None = None) -> None:
        message = f"{entity_name} not found."
        if entity_id is not None:
            message += f" (ID: {entity_id})"
        super().__init__(message)
        self.entity_name = entity_name
        self.entity_id = entity_id


class DuplicateEntryError(RepositoryError):
    """Raised when a unique constraint would be violated on insert/update."""

    def __init__(
        self,
        entity_name: str,
        conflicting_field: str,
        conflicting_value: Any,
    ) -> None:
        message = (
            f"Failed to create {entity_name}. "
            f"An entry with the value '{conflicting_value}' already exists "
            f"for field '{conflicting_field}'."
        )
        super().__init__(message)
        self.entity_name = entity_name
        self.conflicting_field = conflicting_field
        self.conflicting_value = conflicting_value


class ForeignKeyViolationError(RepositoryError):
    """Raised when a referenced related entity does not exist."""

    def __init__(self, message: str = "A related entity does not exist.") -> None:
        super().__init__(message)


# --- Service-layer errors ----------------------------------------------------


class ServiceError(ApplicationError):
    """Base class for service-layer errors."""


class ValidationError(ServiceError):
    """Raised when input data fails validation."""

    def __init__(
        self,
        message: str = "Input data is invalid.",
        context: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.context = context or {}


class PermissionDeniedError(ServiceError):
    """Raised when the caller is authenticated but lacks permission (HTTP 403)."""

    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
    ) -> None:
        super().__init__(message)


class AuthRequiredError(ApplicationError):
    """Raised when an operation requires authentication and none was supplied (HTTP 401)."""

    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(message)


# --- RFC-7807 wire contract --------------------------------------------------


class Error(BaseModel):
    """Default error response shape for HTTP exception handlers.

    A flat RFC-7807-style problem shape: ``message`` is the human-readable
    summary; ``type`` is the application-error class name
    (``NotFoundError``, ``ValidationError``, ...) so a client can dispatch
    on it without parsing the message; ``detail`` carries optional
    structured context (field-level validation errors, conflicting ids,
    a stable error ``code``, a correlation id, etc.).
    """

    message: str
    type: str
    detail: dict | None = None
