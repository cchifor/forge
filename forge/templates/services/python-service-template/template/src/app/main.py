import logging

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router as api_v1_router
from app.core.config import Settings, settings
from app.core.errors import (
    ApplicationError,
    domain_exception_handler,
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.lifecycle import AppLifecycle
from app.middleware.audit import AuditMiddleware
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from service.utils.fastapiutils import Error

logger = logging.getLogger(__name__)


def _configure_middleware(app: FastAPI, settings: Settings) -> None:
    if settings.server.cors and settings.server.cors.enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.server.cors.allow_origins,
            allow_credentials=settings.server.cors.allow_credentials,
            allow_methods=settings.server.cors.allow_methods,
            allow_headers=settings.server.cors.allow_headers,
            max_age=settings.server.cors.max_age,
        )

    excluded_paths = list(settings.audit.excluded_paths) if settings.audit else []
    app.add_middleware(RequestLoggingMiddleware, skip_paths=excluded_paths)

    if settings.audit.enabled:
        app.add_middleware(AuditMiddleware)

    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=120,
        skip_paths=["/health", "/metrics", "/docs", "/openapi.json"],
    )

    # Correlation ID (outermost — runs first, sets context for all inner middleware)
    app.add_middleware(CorrelationIdMiddleware)


def _configure_routers(app: FastAPI) -> None:
    app.include_router(api_v1_router, prefix="/api/v1")


def _configure_exceptions(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ApplicationError, domain_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)


def create_app() -> FastAPI:
    """Application Factory."""
    app = FastAPI(
        **settings.app.model_dump(),
        lifespan=AppLifecycle.lifespan,
        responses={
            status.HTTP_400_BAD_REQUEST: {"model": Error},
            status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": Error},
            status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": Error},
        },
    )

    _configure_middleware(app, settings)
    _configure_exceptions(app)
    _configure_routers(app)
    AppLifecycle.bootstrap(app, settings)

    logger.info("Application factory completed successfully.")
    return app


app = create_app()
