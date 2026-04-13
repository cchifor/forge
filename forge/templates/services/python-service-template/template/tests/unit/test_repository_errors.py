"""Tests for service.repository.errors."""

from service.repository.errors import (
    DuplicateEntryError,
    EntityNotFoundException,
    ForeignKeyViolationError,
    RepositoryException,
)


class TestRepositoryErrors:
    def test_entity_not_found_with_id(self):
        err = EntityNotFoundException("Item", entity_id="abc")
        assert "Item not found" in str(err)
        assert "(ID: abc)" in str(err)

    def test_entity_not_found_no_id(self):
        err = EntityNotFoundException("Item")
        assert "Item not found" in str(err)
        assert "ID" not in str(err)

    def test_repository_exception_default_message(self):
        err = RepositoryException()
        assert "error occurred" in str(err)

    def test_repository_exception_custom_message(self):
        err = RepositoryException("custom error")
        assert str(err) == "custom error"

    def test_duplicate_entry_error(self):
        err = DuplicateEntryError("Item", "name", "Widget")
        assert "Widget" in str(err)
        assert "name" in str(err)

    def test_foreign_key_violation(self):
        err = ForeignKeyViolationError()
        assert "related entity" in str(err)
