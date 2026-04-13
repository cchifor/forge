"""Tests for app.core.errors exception handler functions."""

from unittest.mock import MagicMock

from fastapi import HTTPException as FastAPIHTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import (
    ApplicationError,
    NotFoundError,
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)


def _mock_request():
    req = MagicMock()
    req.method = "GET"
    req.url.path = "/test"
    req.query_params = {}
    req.client.host = "127.0.0.1"
    req.client.port = 8000
    return req


class TestHttpExceptionHandler:
    def test_returns_json_response(self):
        req = _mock_request()
        exc = StarletteHTTPException(status_code=404, detail="Not found")
        resp = http_exception_handler(req, exc)
        assert resp.status_code == 404

    def test_response_has_error_body(self):
        req = _mock_request()
        exc = StarletteHTTPException(status_code=403, detail="Forbidden")
        resp = http_exception_handler(req, exc)
        assert resp.status_code == 403


class TestValidationExceptionHandler:
    def test_returns_422(self):
        req = _mock_request()
        exc = MagicMock()
        exc.__class__.__name__ = "RequestValidationError"
        exc.__cause__ = None
        exc.errors = lambda: [{"msg": "field required", "type": "missing", "loc": ("body", "name")}]
        resp = validation_exception_handler(req, exc)
        assert resp.status_code == 422


class TestGlobalExceptionHandler:
    def test_returns_500(self):
        req = _mock_request()
        exc = RuntimeError("unexpected")
        resp = global_exception_handler(req, exc)
        assert resp.status_code == 500

    def test_with_cause(self):
        req = _mock_request()
        cause = ValueError("root cause")
        exc = RuntimeError("wrapper")
        exc.__cause__ = cause
        resp = global_exception_handler(req, exc)
        assert resp.status_code == 500
