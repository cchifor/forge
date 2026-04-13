"""Tests for the exception hierarchy and HTTP status mapping."""

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
    domain_exception_to_response,
)


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
        exc = NotFoundError("Item", "123")
        response = domain_exception_to_response(exc)
        assert response.status_code == 404

    def test_already_exists_maps_to_409(self):
        exc = AlreadyExistsError("Item")
        response = domain_exception_to_response(exc)
        assert response.status_code == 409

    def test_validation_maps_to_422(self):
        exc = ValidationError("Bad input")
        response = domain_exception_to_response(exc)
        assert response.status_code == 422

    def test_permission_denied_maps_to_403(self):
        exc = PermissionDeniedError()
        response = domain_exception_to_response(exc)
        assert response.status_code == 403

    def test_authorization_maps_to_403(self):
        exc = AuthorizationError()
        response = domain_exception_to_response(exc)
        assert response.status_code == 403

    def test_read_only_maps_to_403(self):
        exc = ReadOnlyError("Template", "abc")
        response = domain_exception_to_response(exc)
        assert response.status_code == 403

    def test_timeout_maps_to_503(self):
        exc = DatabaseTimeoutError()
        response = domain_exception_to_response(exc)
        assert response.status_code == 503

    def test_unmapped_error_maps_to_500(self):
        exc = ApplicationError("Unknown error")
        response = domain_exception_to_response(exc)
        assert response.status_code == 500
