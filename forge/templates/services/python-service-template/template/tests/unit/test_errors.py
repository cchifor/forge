"""Tests for the exception hierarchy and HTTP status mapping."""

import json
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import (
    AlreadyExistsError,
    ApplicationError,
    AuthorizationError,
    DatabaseTimeoutError,
    NotFoundError,
    PermissionDeniedError,
    ReadOnlyError,
    RepositoryError,
    ServiceError,
    ValidationError,
    _serialize_exception,
    domain_exception_handler,
    domain_exception_to_response,
    status_for_code,
)


def _mock_request():
    req = MagicMock()
    req.headers = {"x-correlation-id": "test-corr"}
    req.state.correlation_id = "test-corr"
    return req


class TestExceptionHierarchy:
    def test_not_found_is_repository_error(self):
        assert issubclass(NotFoundError, RepositoryError)
        assert issubclass(RepositoryError, ApplicationError)

    def test_already_exists_is_service_error(self):
        assert issubclass(AlreadyExistsError, ServiceError)
        assert issubclass(ServiceError, ApplicationError)

    def test_not_found_message(self):
        exc = NotFoundError("Item", "abc-123")
        assert "Item not found" in str(exc)
        assert "abc-123" in str(exc)

    def test_not_found_message_no_id(self):
        exc = NotFoundError("Item")
        assert str(exc) == "Item not found."

    def test_already_exists_message(self):
        exc = AlreadyExistsError("Item", "my-item")
        assert "Item already exists" in str(exc)
        assert "my-item" in str(exc)


class TestDomainErrorMapping:
    def test_not_found_maps_to_404(self):
        response = domain_exception_to_response(_mock_request(), NotFoundError("Item", "123"))
        assert response.status_code == 404

    def test_already_exists_maps_to_409(self):
        response = domain_exception_to_response(_mock_request(), AlreadyExistsError("Item"))
        assert response.status_code == 409

    def test_validation_maps_to_422(self):
        response = domain_exception_to_response(_mock_request(), ValidationError("Bad input"))
        assert response.status_code == 422

    def test_permission_denied_maps_to_403(self):
        response = domain_exception_to_response(_mock_request(), PermissionDeniedError())
        assert response.status_code == 403

    def test_authorization_maps_to_403(self):
        response = domain_exception_to_response(_mock_request(), AuthorizationError())
        assert response.status_code == 403

    def test_read_only_maps_to_403(self):
        response = domain_exception_to_response(
            _mock_request(), ReadOnlyError("Template", "abc")
        )
        assert response.status_code == 403

    def test_timeout_maps_to_503(self):
        response = domain_exception_to_response(_mock_request(), DatabaseTimeoutError())
        assert response.status_code == 503

    def test_unmapped_error_maps_to_500(self):
        response = domain_exception_to_response(_mock_request(), ApplicationError("Unknown"))
        assert response.status_code == 500


class TestErrorPortRuntimeWiring:
    """E.1.b: the central domain handler delegates to the registered
    ``ErrorPort`` adapter so the runtime path actually exercises the
    port. The wire shape stays RFC-007 (``{"error": {"code", "message",
    "type", "context", "correlation_id"}}``) regardless of which path
    the serialiser seam resolves to — that's the cross-stack invariant."""

    def test_serializer_seam_is_callable(self):
        """The module-level seam is bound either to ``DefaultErrorPort``
        (when the fragment shipped its adapter) or the inline fallback.
        Either way it must accept an ``Exception`` and return the
        RFC-007 envelope dict."""
        envelope = _serialize_exception(NotFoundError("Item", "abc-123"))
        assert "error" in envelope
        err = envelope["error"]
        for field in ("code", "message", "type", "context", "correlation_id"):
            assert field in err, f"envelope missing required field: {field!r}"
        assert err["code"] == "NOT_FOUND"
        assert err["type"] == "NotFoundError"
        assert err["context"] == {"entity": "Item", "id": "abc-123"}

    def test_serializer_seam_falls_back_for_unknown_exceptions(self):
        """Anything outside the ``ApplicationError`` hierarchy serialises
        as a redacted ``INTERNAL_ERROR`` envelope — same shape, generic
        code. Confirms the fallback branch on both the port adapter and
        the inline serialiser."""
        envelope = _serialize_exception(RuntimeError("boom"))
        err = envelope["error"]
        assert err["code"] == "INTERNAL_ERROR"
        assert err["message"] == "An unexpected error occurred"
        assert err["context"] == {}

    def test_status_for_code_reverse_maps_canonical_codes(self):
        """The port owns the envelope wire shape; HTTP status mapping
        stays in the handler. ``status_for_code`` is the helper the
        handler uses to bridge code → HTTP status after the port
        produces the envelope."""
        assert status_for_code("NOT_FOUND") == 404
        assert status_for_code("ALREADY_EXISTS") == 409
        assert status_for_code("VALIDATION_FAILED") == 422
        assert status_for_code("AUTH_REQUIRED") == 401
        assert status_for_code("PERMISSION_DENIED") == 403
        assert status_for_code("RATE_LIMITED") == 429
        # Unknown codes are loud-but-recoverable — fall to 500.
        assert status_for_code("DEFINITELY_NOT_A_REAL_CODE") == 500

    def test_domain_handler_round_trip_emits_rfc007_envelope(self):
        """End-to-end: raise an ``ApplicationError`` from a real
        FastAPI route, register the domain handler, and assert the
        response body matches RFC-007 EXACTLY (parsed JSON) with the
        correct HTTP status. The ``X-Correlation-Id`` header must
        round-trip into ``correlation_id`` on the envelope."""
        app = FastAPI()
        app.add_exception_handler(ApplicationError, domain_exception_handler)

        @app.get("/missing")
        def missing():
            raise NotFoundError("Item", "abc-123")

        client = TestClient(app)
        correlation_id = "test-corr-xyz-42"
        response = client.get(
            "/missing", headers={"X-Correlation-Id": correlation_id}
        )

        assert response.status_code == 404
        body = json.loads(response.text)
        assert set(body.keys()) == {"error"}
        err = body["error"]
        assert set(err.keys()) == {
            "code",
            "message",
            "type",
            "context",
            "correlation_id",
        }
        assert err["code"] == "NOT_FOUND"
        assert err["type"] == "NotFoundError"
        assert err["context"] == {"entity": "Item", "id": "abc-123"}
        assert err["correlation_id"] == correlation_id
        assert err["message"]  # non-empty

    def test_domain_handler_round_trip_for_validation_error(self):
        """A different exception type to make sure the status mapping
        works across codes. ``ValidationError`` → ``422 VALIDATION_FAILED``."""
        app = FastAPI()
        app.add_exception_handler(ApplicationError, domain_exception_handler)

        @app.get("/invalid")
        def invalid():
            raise ValidationError("email is required", context={"field": "email"})

        client = TestClient(app)
        response = client.get(
            "/invalid", headers={"X-Correlation-Id": "corr-validation"}
        )

        assert response.status_code == 422
        err = json.loads(response.text)["error"]
        assert err["code"] == "VALIDATION_FAILED"
        assert err["type"] == "ValidationError"
        assert err["context"] == {"field": "email"}
        assert err["correlation_id"] == "corr-validation"
