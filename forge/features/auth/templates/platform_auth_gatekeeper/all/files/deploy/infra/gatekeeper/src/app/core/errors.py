import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class Error(BaseModel):
    """Standard error response model."""

    message: str
    type: str
    detail: dict | None = None


# --- Exception Handlers ---


def _log_error(request: Request, exc: Exception, status_code: int) -> None:
    error_details = {
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "error_type": exc.__class__.__name__,
        "message": str(exc),
    }
    logger.error("Request Failed: %s", error_details)


def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _log_error(request, exc, getattr(exc, "status_code", 500))
    if not isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=500,
            content=Error(
                message="Internal Server Error", type="HTTPException"
            ).model_dump(),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=Error(
            message=str(exc.detail),
            type="HTTPException",
            detail={"code": exc.status_code},
        ).model_dump(),
    )


def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _log_error(request, exc, 422)
    errors_callable = getattr(exc, "errors", None)
    raw_errors = errors_callable() if callable(errors_callable) else []
    errors = {f"{err['msg']}: {err['type']} {err['loc']}" for err in raw_errors}
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=Error(
            message=f"Validation Error: {', '.join(errors)}",
            type="ValidationError",
            detail={"errors": list(errors)},
        ).model_dump(),
    )


def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _log_error(request, exc, 500)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=Error(
            message="Internal Server Error",
            type="ServerException",
        ).model_dump(),
    )
