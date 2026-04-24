"""Tests for app.core.errors exception handler functions."""

import json
from unittest.mock import MagicMock

from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import (
    AlreadyExistsError,
    ApplicationError,
    AuthRequiredError,
    DatabaseTimeoutError,
    DuplicateEntryError,
    NotFoundError,
    PermissionDeniedError,
    ReadOnlyError,
    ValidationError,
    domain_exception_handler,
    global_exception_handler,
    http_exception_handler,
    register_domain_error,
    validation_exception_handler,
)


def _mock_request(correlation_id: str = "corr-test-1"):
    req = MagicMock()
    req.method = "GET"
    req.url.path = "/test"
    req.query_params = {}
    req.client.host = "127.0.0.1"
    req.client.port = 8000
    headers = {}
    if correlation_id:
        headers["x-correlation-id"] = correlation_id
    req.headers = headers
    req.state.correlation_id = correlation_id
    return req


def _body(resp) -> dict:
    return json.loads(bytes(resp.body).decode("utf-8"))


class TestRFC007Envelope:
    def test_http_exception_maps_404_to_not_found_code(self):
        req = _mock_request()
        exc = StarletteHTTPException(status_code=404, detail="Missing")
        resp = http_exception_handler(req, exc)
        assert resp.status_code == 404
        body = _body(resp)
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["message"] == "Missing"
        assert body["error"]["type"] == "HTTPException"
        assert body["error"]["correlation_id"] == "corr-test-1"
        assert body["error"]["context"] == {}

    def test_http_exception_401_maps_to_auth_required(self):
        req = _mock_request()
        exc = StarletteHTTPException(status_code=401, detail="no token")
        resp = http_exception_handler(req, exc)
        assert _body(resp)["error"]["code"] == "AUTH_REQUIRED"

    def test_validation_exception_emits_422(self):
        req = _mock_request()
        exc = MagicMock()
        exc.__class__.__name__ = "RequestValidationError"
        exc.__cause__ = None
        exc.errors = lambda: [
            {"msg": "field required", "type": "missing", "loc": ("body", "name")}
        ]
        resp = validation_exception_handler(req, exc)
        assert resp.status_code == 422
        body = _body(resp)
        assert body["error"]["code"] == "VALIDATION_FAILED"
        assert body["error"]["context"]["errors"][0]["msg"] == "field required"

    def test_global_exception_hides_internals(self):
        req = _mock_request()
        resp = global_exception_handler(req, RuntimeError("secret stack trace"))
        assert resp.status_code == 500
        body = _body(resp)
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "secret" not in body["error"]["message"]

    def test_domain_not_found(self):
        req = _mock_request()
        exc = NotFoundError("Item", "abc")
        resp = domain_exception_handler(req, exc)
        assert resp.status_code == 404
        body = _body(resp)
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["type"] == "NotFoundError"
        assert body["error"]["context"] == {"entity": "Item", "id": "abc"}

    def test_domain_already_exists(self):
        req = _mock_request()
        resp = domain_exception_handler(req, AlreadyExistsError("Item", "dup"))
        body = _body(resp)
        assert resp.status_code == 409
        assert body["error"]["code"] == "ALREADY_EXISTS"
        assert body["error"]["context"] == {"entity": "Item", "id": "dup"}

    def test_domain_duplicate_entry_context(self):
        req = _mock_request()
        resp = domain_exception_handler(
            req, DuplicateEntryError("Item", "name", "dup-name")
        )
        body = _body(resp)
        assert resp.status_code == 409
        assert body["error"]["code"] == "DUPLICATE_ENTRY"
        assert body["error"]["context"] == {
            "entity": "Item",
            "field": "name",
            "value": "dup-name",
        }

    def test_domain_validation_passes_context(self):
        req = _mock_request()
        resp = domain_exception_handler(
            req, ValidationError("Email invalid", context={"field": "email"})
        )
        body = _body(resp)
        assert resp.status_code == 422
        assert body["error"]["code"] == "VALIDATION_FAILED"
        assert body["error"]["context"] == {"field": "email"}

    def test_domain_permission_denied(self):
        req = _mock_request()
        resp = domain_exception_handler(req, PermissionDeniedError())
        assert resp.status_code == 403
        assert _body(resp)["error"]["code"] == "PERMISSION_DENIED"

    def test_domain_read_only(self):
        req = _mock_request()
        resp = domain_exception_handler(req, ReadOnlyError("Item", "abc"))
        body = _body(resp)
        assert resp.status_code == 403
        assert body["error"]["code"] == "READ_ONLY"
        assert body["error"]["context"] == {"resource": "Item", "id": "abc"}

    def test_domain_auth_required(self):
        req = _mock_request()
        resp = domain_exception_handler(req, AuthRequiredError())
        assert resp.status_code == 401
        assert _body(resp)["error"]["code"] == "AUTH_REQUIRED"

    def test_database_timeout_is_503(self):
        req = _mock_request()
        resp = domain_exception_handler(req, DatabaseTimeoutError())
        assert resp.status_code == 503
        assert _body(resp)["error"]["code"] == "DATABASE_TIMEOUT"

    def test_correlation_id_from_x_request_id(self):
        req = _mock_request(correlation_id="")
        req.headers = {"x-request-id": "req-123"}
        resp = domain_exception_handler(req, NotFoundError("Item", "x"))
        assert _body(resp)["error"]["correlation_id"] == "req-123"

    def test_unregistered_application_error_is_internal(self):
        class Whatever(ApplicationError):
            pass

        req = _mock_request()
        resp = domain_exception_handler(req, Whatever("boom"))
        assert resp.status_code == 500
        assert _body(resp)["error"]["code"] == "INTERNAL_ERROR"


class TestRegisterDomainError:
    def test_can_register_new_error(self):
        class QuotaExceededError(ApplicationError):
            pass

        register_domain_error(QuotaExceededError, "QUOTA_EXCEEDED", 429)
        req = _mock_request()
        resp = domain_exception_handler(req, QuotaExceededError("limit"))
        assert resp.status_code == 429
        assert _body(resp)["error"]["code"] == "QUOTA_EXCEEDED"

    def test_idempotent_for_identical_registration(self):
        class IdempotentError(ApplicationError):
            pass

        register_domain_error(IdempotentError, "IDEMPOTENT", 418)
        register_domain_error(IdempotentError, "IDEMPOTENT", 418)

    def test_rejects_conflicting_registration(self):
        class ConflictErr(ApplicationError):
            pass

        register_domain_error(ConflictErr, "CONFLICT_A", 409)
        import pytest

        with pytest.raises(ValueError, match="already registered"):
            register_domain_error(ConflictErr, "CONFLICT_B", 400)
