"""Tests for the service-layer exception hierarchy."""

from __future__ import annotations

from service.core.errors import (
    ApplicationError,
    PermissionDeniedError,
    ServiceError,
    ValidationError,
)


class TestErrorHierarchy:
    def test_service_error_is_application_error(self):
        assert issubclass(ServiceError, ApplicationError)

    def test_validation_error_is_service_error(self):
        assert issubclass(ValidationError, ServiceError)

    def test_permission_denied_is_service_error(self):
        assert issubclass(PermissionDeniedError, ServiceError)

    def test_all_are_exceptions(self):
        for cls in (ApplicationError, ServiceError,
                    ValidationError, PermissionDeniedError):
            assert issubclass(cls, Exception)


class TestApplicationError:
    def test_custom_message(self):
        err = ApplicationError("something broke")
        assert err.message == "something broke"
        assert str(err) == "something broke"

    def test_default_message(self):
        err = ApplicationError()
        assert err.message == "An application error occurred."


class TestValidationError:
    def test_default_message(self):
        err = ValidationError()
        assert str(err) == "Input data is invalid."

    def test_custom_message(self):
        err = ValidationError("bad field")
        assert str(err) == "bad field"

    def test_isinstance(self):
        err = ValidationError()
        assert isinstance(err, ServiceError)
        assert isinstance(err, ApplicationError)


class TestPermissionDeniedError:
    def test_default_message(self):
        err = PermissionDeniedError()
        assert "permission" in str(err).lower()

    def test_custom_message(self):
        err = PermissionDeniedError("nope")
        assert str(err) == "nope"

    def test_isinstance(self):
        err = PermissionDeniedError()
        assert isinstance(err, ServiceError)
        assert isinstance(err, ApplicationError)
