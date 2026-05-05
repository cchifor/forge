import logging
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from service.utils.fastapiutils import ErrorEnvelope, ErrorBody

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
        self.entity_name = entity_name
        self.entity_id = entity_id


class DuplicateEntryError(RepositoryError):
    def __init__(self, entity_name: str, conflicting_field: str, conflicting_value: Any):
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


class DatabaseUnavailableError(RepositoryError):
    def __init__(self, message="The database is unavailable."):
        super().__init__(message)


# --- Service Layer Errors ---


class ServiceError(ApplicationError):
    pass


class ValidationError(ServiceError):
    def __init__(self, message="Input data is invalid.", context: dict | None = None):
        super().__init__(message)
        self.context = context or {}


class PermissionDeniedError(ServiceError):
    def __init__(self, message="You do not have permission to perform this action."):
        super().__init__(message)


class AlreadyExistsError(ServiceError):
    def __init__(self, name: str, identifier: Any = None):
        self.name = name
        self.identifier = identifier
        message = f"{name} already exists."
        if identifier is not None:
            message += f" (Identifier: {identifier})"
        super().__init__(message)


class AuthorizationError(ApplicationError):
    def __init__(self, message="User is not authorized for this operation."):
        super().__init__(message)


class AuthRequiredError(ApplicationError):
    def __init__(self, message="Authentication required."):
        super().__init__(message)


class ReadOnlyError(ServiceError):
    def __init__(self, resource: str, identifier: Any = None):
        self.resource = resource
        self.identifier = identifier
        message = f"{resource} is read-only and cannot be modified."
        if identifier is not None:
            message += f" (ID: {identifier})"
        super().__init__(message)


class RateLimitedError(ApplicationError):
    def __init__(self, message="Too many requests. Please retry later."):
        super().__init__(message)


class DependencyUnavailableError(ApplicationError):
    def __init__(self, dependency: str, message: str | None = None):
        self.dependency = dependency
        super().__init__(message or f"{dependency} is unavailable.")


# --- RFC-007 Error Contract Mapping ---
#
# Each registered `ApplicationError` subclass maps to a stable (code, status)
# pair that every backend emits identically. Fragments that define their own
# `ApplicationError` subclasses should register at import time via
# `register_domain_error` — duplicate registration with a conflicting code
# or status raises, so two features cannot silently claim the same mapping.


_DOMAIN_ERROR_MAP: dict[type[ApplicationError], tuple[str, int]] = {
    AuthRequiredError: ("AUTH_REQUIRED", status.HTTP_401_UNAUTHORIZED),
    AuthorizationError: ("PERMISSION_DENIED", status.HTTP_403_FORBIDDEN),
    PermissionDeniedError: ("PERMISSION_DENIED", status.HTTP_403_FORBIDDEN),
    ReadOnlyError: ("READ_ONLY", status.HTTP_403_FORBIDDEN),
    NotFoundError: ("NOT_FOUND", status.HTTP_404_NOT_FOUND),
    AlreadyExistsError: ("ALREADY_EXISTS", status.HTTP_409_CONFLICT),
    DuplicateEntryError: ("DUPLICATE_ENTRY", status.HTTP_409_CONFLICT),
    ForeignKeyViolationError: ("FOREIGN_KEY_VIOLATION", status.HTTP_409_CONFLICT),
    ConstraintViolationError: ("CONSTRAINT_VIOLATION", status.HTTP_409_CONFLICT),
    NotNullViolationError: ("CONSTRAINT_VIOLATION", status.HTTP_409_CONFLICT),
    ValidationError: ("VALIDATION_FAILED", status.HTTP_422_UNPROCESSABLE_CONTENT),
    DataValidationError: ("VALIDATION_FAILED", status.HTTP_422_UNPROCESSABLE_CONTENT),
    RateLimitedError: ("RATE_LIMITED", status.HTTP_429_TOO_MANY_REQUESTS),
    DatabaseTimeoutError: ("DATABASE_TIMEOUT", status.HTTP_503_SERVICE_UNAVAILABLE),
    DatabaseUnavailableError: ("DATABASE_UNAVAILABLE", status.HTTP_503_SERVICE_UNAVAILABLE),
    DependencyUnavailableError: ("DEPENDENCY_UNAVAILABLE", status.HTTP_503_SERVICE_UNAVAILABLE),
}


def register_domain_error(
    exc_type: type[ApplicationError],
    code: str,
    status_code: int,
) -> None:
    """Register a fragment-owned :class:`ApplicationError` subclass.

    Call at module-import time. Re-registering with a conflicting
    `(code, status_code)` raises to catch two features claiming the
    same exception type silently.
    """
    existing = _DOMAIN_ERROR_MAP.get(exc_type)
    if existing is not None and existing != (code, status_code):
        raise ValueError(
            f"{exc_type.__name__} already registered as {existing}; "
            f"refusing re-register as ({code!r}, {status_code})."
        )
    _DOMAIN_ERROR_MAP[exc_type] = (code, status_code)


def _lookup_mapping(exc: ApplicationError) -> tuple[str, int]:
    for cls in type(exc).__mro__:
        if cls in _DOMAIN_ERROR_MAP:
            # ``cls`` from ``__mro__`` is plain ``type``; ty's narrowing won't
            # walk the MRO to confirm it's an ``ApplicationError`` subclass.
            return _DOMAIN_ERROR_MAP[cls]  # ty: ignore[invalid-argument-type]
    return "INTERNAL_ERROR", status.HTTP_500_INTERNAL_SERVER_ERROR


def _correlation_id(request: Request) -> str:
    header = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
    if header:
        return header
    return getattr(request.state, "correlation_id", "") or ""


def _context_for(exc: ApplicationError) -> dict:
    """Surface structured context from well-known error classes."""
    if isinstance(exc, NotFoundError):
        return {"entity": exc.entity_name, "id": exc.entity_id}
    if isinstance(exc, AlreadyExistsError):
        return {"entity": exc.name, "id": exc.identifier}
    if isinstance(exc, DuplicateEntryError):
        return {
            "entity": exc.entity_name,
            "field": exc.conflicting_field,
            "value": exc.conflicting_value,
        }
    if isinstance(exc, ReadOnlyError):
        return {"resource": exc.resource, "id": exc.identifier}
    if isinstance(exc, ValidationError):
        return exc.context
    if isinstance(exc, DependencyUnavailableError):
        return {"dependency": exc.dependency}
    return {}


def _envelope(
    request: Request,
    *,
    code: str,
    message: str,
    type_name: str,
    context: dict | None = None,
    status_code: int,
) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            type=type_name,
            context=context or {},
            correlation_id=_correlation_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def domain_exception_to_response(request: Request, exc: ApplicationError) -> JSONResponse:
    code, status_code = _lookup_mapping(exc)
    return _envelope(
        request,
        code=code,
        message=str(exc),
        type_name=type(exc).__name__,
        context=_context_for(exc),
        status_code=status_code,
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
        "correlation_id": _correlation_id(request),
    }
    if exc.__cause__:
        error_details["inner_error_type"] = exc.__cause__.__class__.__name__
        error_details["inner_message"] = str(exc.__cause__)
    logger.error(f"Request Failed: {error_details}")


# --- Exception Handlers ---


def http_exception_handler(request: Request, exc: Exception):
    assert isinstance(exc, StarletteHTTPException)
    status_code = exc.status_code
    _log_error(request, exc, status_code)
    code = "INVALID_INPUT" if 400 <= status_code < 500 else "INTERNAL_ERROR"
    if status_code == 401:
        code = "AUTH_REQUIRED"
    elif status_code == 403:
        code = "PERMISSION_DENIED"
    elif status_code == 404:
        code = "NOT_FOUND"
    elif status_code == 429:
        code = "RATE_LIMITED"
    return _envelope(
        request,
        code=code,
        message=str(exc.detail),
        type_name="HTTPException",
        status_code=status_code,
    )


def validation_exception_handler(request: Request, exc: Exception):
    _log_error(request, exc, 422)
    errors = [
        {"msg": err.get("msg"), "type": err.get("type"), "loc": err.get("loc")}
        for err in getattr(exc, "errors", lambda: [])()
    ]
    message = "Validation failed"
    if errors:
        message += ": " + "; ".join(f"{e['msg']} ({e['type']})" for e in errors)
    return _envelope(
        request,
        code="VALIDATION_FAILED",
        message=message,
        type_name="ValidationError",
        context={"errors": errors},
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


def domain_exception_handler(request: Request, exc: Exception):
    assert isinstance(exc, ApplicationError)
    code, status_code = _lookup_mapping(exc)
    _log_error(request, exc, status_code)
    return domain_exception_to_response(request, exc)


def global_exception_handler(request: Request, exc: Exception):
    _log_error(request, exc, status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _envelope(
        request,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred",
        type_name="InternalError",
        context={"note": "Check server logs for the correlation id"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
