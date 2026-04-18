import logging
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from service.utils.fastapiutils import Error

logger = logging.getLogger("app.errors")


# --- Application Error Hierarchy ---


class ApplicationError(Exception):
    """Base class for all application-specific errors."""

    @property
    def message(self):
        return self.args[0] if self.args else "An application error occurred."


# --- Repository & Database Errors ---


class RepositoryError(ApplicationError):
    pass


class NotFoundError(RepositoryError):
    def __init__(self, entity_name: str, entity_id: Any | None = None):
        message = f"{entity_name} not found."
        if entity_id is not None:
            message += f" (ID: {entity_id})"
        super().__init__(message)


class DuplicateEntryError(RepositoryError):
    def __init__(self, entity_name: str, conflicting_field: str, conflicting_value: Any):
        message = (
            f"Failed to create {entity_name}. "
            f"An entry with the value '{conflicting_value}' already exists "
            f"for field '{conflicting_field}'."
        )
        super().__init__(message)


class ForeignKeyViolationError(RepositoryError):
    def __init__(self, message="A related entity does not exist."):
        super().__init__(message)


class NotNullViolationError(RepositoryError):
    def __init__(self, message="A required field was left empty."):
        super().__init__(message)


class ConstraintViolationError(RepositoryError):
    def __init__(self, message="A database constraint was violated."):
        super().__init__(message)


class DataValidationError(RepositoryError):
    def __init__(self, message="The provided data is invalid."):
        super().__init__(message)


class DatabaseTimeoutError(RepositoryError):
    def __init__(self, message="The database operation timed out. Please try again later."):
        super().__init__(message)


# --- Service Layer Errors ---


class ServiceError(ApplicationError):
    pass


class ValidationError(ServiceError):
    def __init__(self, message="Input data is invalid."):
        super().__init__(message)


class PermissionDeniedError(ServiceError):
    def __init__(self, message="You do not have permission to perform this action."):
        super().__init__(message)


class AlreadyExistsError(ServiceError):
    def __init__(self, name: str, identifier: Any = None):
        self.name = name
        message = f"{name} already exists."
        if identifier is not None:
            message += f" (Identifier: {identifier})"
        super().__init__(message)


class AuthorizationError(ApplicationError):
    def __init__(self, message="User is not authorized for this operation."):
        super().__init__(message)


class ReadOnlyError(ServiceError):
    def __init__(self, resource: str, identifier: Any = None):
        message = f"{resource} is read-only and cannot be modified."
        if identifier is not None:
            message += f" (ID: {identifier})"
        super().__init__(message)


# --- Domain Error -> HTTP Status Mapping ---
#
# Fragments that define their own `ServiceError` / `RepositoryError`
# subclasses should register them at import time via `register_domain_error`
# rather than swallowing the exception and raising `HTTPException` inline.
# That way the central handler produces a uniform error envelope and the
# observability plumbing (log shape, tags, tracing) stays consistent.

_DOMAIN_ERROR_MAP: dict[type[ApplicationError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    AlreadyExistsError: status.HTTP_409_CONFLICT,
    DuplicateEntryError: status.HTTP_409_CONFLICT,
    ValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    DataValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    AuthorizationError: status.HTTP_403_FORBIDDEN,
    ReadOnlyError: status.HTTP_403_FORBIDDEN,
    DatabaseTimeoutError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def register_domain_error(exc_type: type[ApplicationError], status_code: int) -> None:
    """Register a fragment-owned `ApplicationError` subclass with its HTTP
    status. Call from the fragment's import-time setup (top of a
    module that gets loaded during app bootstrap).

    Re-registering with a different status code raises — this catches
    two features accidentally claiming the same exception type.
    """
    existing = _DOMAIN_ERROR_MAP.get(exc_type)
    if existing is not None and existing != status_code:
        raise ValueError(
            f"{exc_type.__name__} is already registered with status "
            f"{existing}; refusing re-register as {status_code}."
        )
    _DOMAIN_ERROR_MAP[exc_type] = status_code


def domain_exception_to_response(exc: ApplicationError) -> JSONResponse:
    for cls in type(exc).__mro__:
        if cls in _DOMAIN_ERROR_MAP:
            status_code = _DOMAIN_ERROR_MAP[cls]
            break
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    return JSONResponse(
        status_code=status_code,
        content=Error(
            message=str(exc),
            type=type(exc).__name__,
            detail={"code": status_code},
        ).model_dump(),
    )


def _log_error(request: Request, exc: Exception, status_code: int):
    error_details = {
        "method": request.method,
        "path": request.url.path,
        "query": dict(request.query_params),
        "client": f"{request.client.host}:{request.client.port}" if request.client else "unknown",
        "status_code": status_code,
        "error_type": exc.__class__.__name__,
        "message": str(exc),
    }
    if exc.__cause__:
        error_details["inner_error_type"] = exc.__cause__.__class__.__name__
        error_details["inner_message"] = str(exc.__cause__)
    logger.error(f"Request Failed: {error_details}")


# --- Exception Handlers ---


def http_exception_handler(request: Request, exc: Exception):
    _log_error(request, exc, getattr(exc, "status_code", 500))
    assert isinstance(exc, StarletteHTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content=Error(
            message=str(exc.detail),
            type="HTTPException",
            detail={"code": exc.status_code},
        ).model_dump(),
    )


def validation_exception_handler(request: Request, exc: Exception):
    _log_error(request, exc, 422)
    errors = {
        f"{err['msg']}: {err['type']} {err['loc']}" for err in getattr(exc, "errors", lambda: [])()
    }
    message = f"Validation Error: {', '.join(errors)}"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=Error(
            message=message, type="ValidationError", detail={"errors": list(errors)}
        ).model_dump(),
    )


def domain_exception_handler(request: Request, exc: Exception):
    assert isinstance(exc, ApplicationError)
    _log_error(request, exc, status.HTTP_400_BAD_REQUEST)
    return domain_exception_to_response(exc)


def global_exception_handler(request: Request, exc: Exception):
    _log_error(request, exc, status.HTTP_500_INTERNAL_SERVER_ERROR)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=Error(
            message="Internal Server Error",
            type="ServerException",
            detail={"note": "Check server logs for trace id"},
        ).model_dump(),
    )
