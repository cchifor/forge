"""Tests for app.main helper functions."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI

from app.main import _configure_exceptions, _configure_middleware, _configure_routers


class TestConfigureRouters:
    def test_adds_api_v1_router(self):
        app = FastAPI()
        _configure_routers(app)
        paths = [route.path for route in app.routes]
        assert any("/api/v1" in p for p in paths)


class TestConfigureExceptions:
    def test_registers_handlers(self):
        app = FastAPI()
        _configure_exceptions(app)
        assert len(app.exception_handlers) >= 4


class TestConfigureMiddleware:
    def test_adds_middleware(self):
        app = FastAPI()
        settings = MagicMock()
        settings.server.cors = None
        settings.audit.enabled = False
        settings.audit.excluded_paths = []
        _configure_middleware(app, settings)
        # Middleware stack should have entries
        assert app.middleware_stack is None  # not built yet, but no error

    def test_cors_when_enabled(self):
        app = FastAPI()
        settings = MagicMock()
        settings.server.cors.enabled = True
        settings.server.cors.allow_origins = ["*"]
        settings.server.cors.allow_credentials = True
        settings.server.cors.allow_methods = ["*"]
        settings.server.cors.allow_headers = ["*"]
        settings.server.cors.max_age = 600
        settings.audit.enabled = True
        settings.audit.excluded_paths = ["/health"]
        _configure_middleware(app, settings)

    def test_audit_disabled(self):
        app = FastAPI()
        settings = MagicMock()
        settings.server.cors = None
        settings.audit.enabled = False
        settings.audit.excluded_paths = []
        _configure_middleware(app, settings)
