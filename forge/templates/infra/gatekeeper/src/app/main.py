# src/app/main.py
"""
Gatekeeper — OIDC Relying Party & Traefik ForwardAuth gateway.

Lightweight auth-proxy exposing ``/auth``, ``/callback``, ``/logout``
and a simple ``/health`` endpoint.
"""

import logging

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router as api_v1_router
from app.core.config import Settings, settings
from app.core.errors import (
    Error,
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.lifecycle import AppLifecycle
from app.gatekeeper.routes import router as gatekeeper_router
from app.middleware.logging import RequestLoggingMiddleware

logger = logging.getLogger(__name__)


def _configure_middleware(app: FastAPI, cfg: Settings) -> None:
    """Configure application middleware stack."""
    if cfg.server.cors and cfg.server.cors.enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.server.cors.allow_origins,
            allow_credentials=cfg.server.cors.allow_credentials,
            allow_methods=cfg.server.cors.allow_methods,
            allow_headers=cfg.server.cors.allow_headers,
            max_age=cfg.server.cors.max_age,
        )

    excluded_paths = list(cfg.audit.excluded_paths)
    app.add_middleware(RequestLoggingMiddleware, skip_paths=excluded_paths)


def _configure_routers(app: FastAPI) -> None:
    """Register API routers."""
    # Gatekeeper auth routes (top-level: /auth, /callback, /logout)
    app.include_router(gatekeeper_router)

    # Service meta endpoints (health, info)
    app.include_router(api_v1_router, prefix="/api/v1")


def _configure_exceptions(app: FastAPI) -> None:
    """Register global exception handlers."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)


# ── Factory ─────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Application Factory."""
    app = FastAPI(
        **settings.app.model_dump(),
        lifespan=AppLifecycle.lifespan,
        responses={
            status.HTTP_400_BAD_REQUEST: {"model": Error},
            status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": Error},
        },
    )

    _configure_middleware(app, settings)
    _configure_exceptions(app)
    _configure_routers(app)
    AppLifecycle.bootstrap(app, settings)

    logger.info("Application factory completed successfully.")
    return app


# Uvicorn entry point
app = create_app()
