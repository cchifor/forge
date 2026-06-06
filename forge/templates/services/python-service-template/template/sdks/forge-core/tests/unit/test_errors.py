"""Contract tests for the forge-core error hierarchy and wire model.

The class names, the inheritance tree and the :class:`Error` field shape
are part of the public contract — service code dispatches on the exception
types and clients parse the wire model — so they're pinned here to catch an
accidental rename / reshape in a refactor.
"""

from __future__ import annotations

import pytest

from forge_core.errors import (
    ApplicationError,
    AuthRequiredError,
    DuplicateEntryError,
    Error,
    ForeignKeyViolationError,
    NotFoundError,
    PermissionDeniedError,
    RepositoryError,
    ServiceError,
    ValidationError,
)


class TestHierarchy:
    def test_repository_errors_descend_from_repository_error(self) -> None:
        for exc_cls in (NotFoundError, DuplicateEntryError, ForeignKeyViolationError):
            assert issubclass(exc_cls, RepositoryError)
            assert issubclass(exc_cls, ApplicationError)

    def test_service_errors_descend_from_service_error(self) -> None:
        for exc_cls in (ValidationError, PermissionDeniedError):
            assert issubclass(exc_cls, ServiceError)
            assert issubclass(exc_cls, ApplicationError)

    def test_auth_required_is_application_error(self) -> None:
        assert issubclass(AuthRequiredError, ApplicationError)
        # 401 (no/expired creds) is distinct from 403 (creds present, denied).
        assert not issubclass(AuthRequiredError, PermissionDeniedError)

    def test_application_error_is_an_exception(self) -> None:
        assert issubclass(ApplicationError, Exception)


class TestApplicationError:
    def test_message_property_returns_first_arg(self) -> None:
        assert ApplicationError("boom").message == "boom"

    def test_message_property_has_default_when_no_args(self) -> None:
        assert ApplicationError().message == "An application error occurred."


class TestNotFoundError:
    def test_message_without_id(self) -> None:
        exc = NotFoundError("Item")
        assert str(exc) == "Item not found."
        assert exc.entity_name == "Item"
        assert exc.entity_id is None

    def test_message_with_id(self) -> None:
        exc = NotFoundError("Item", entity_id=42)
        assert str(exc) == "Item not found. (ID: 42)"
        assert exc.entity_id == 42


class TestDuplicateEntryError:
    def test_carries_conflict_context(self) -> None:
        exc = DuplicateEntryError("User", "email", "a@b.com")
        assert exc.entity_name == "User"
        assert exc.conflicting_field == "email"
        assert exc.conflicting_value == "a@b.com"
        assert "already exists" in str(exc)


class TestForeignKeyViolationError:
    def test_default_message(self) -> None:
        assert str(ForeignKeyViolationError()) == "A related entity does not exist."

    def test_custom_message(self) -> None:
        assert str(ForeignKeyViolationError("no parent")) == "no parent"


class TestValidationError:
    def test_default_message_and_empty_context(self) -> None:
        exc = ValidationError()
        assert str(exc) == "Input data is invalid."
        assert exc.context == {}

    def test_carries_context(self) -> None:
        exc = ValidationError("bad", context={"field": "name"})
        assert exc.context == {"field": "name"}


class TestPermissionDeniedError:
    def test_default_message(self) -> None:
        assert "permission" in str(PermissionDeniedError()).lower()


class TestAuthRequiredError:
    def test_default_message(self) -> None:
        assert str(AuthRequiredError()) == "Authentication required."


class TestErrorWireModel:
    def test_minimal_shape(self) -> None:
        body = Error(message="nope", type="NotFoundError")
        assert body.model_dump() == {"message": "nope", "type": "NotFoundError", "detail": None}

    def test_detail_carries_structured_context(self) -> None:
        body = Error(
            message="conflict",
            type="DuplicateEntryError",
            detail={"code": "DUPLICATE_ENTRY", "field": "email"},
        )
        dumped = body.model_dump()
        assert dumped["detail"] == {"code": "DUPLICATE_ENTRY", "field": "email"}

    def test_message_and_type_are_required(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            Error(message="missing type")  # type: ignore[call-arg]
