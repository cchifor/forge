from typing import Any

from service.core.errors import ApplicationError


class RepositoryError(ApplicationError):
    """Base class for repository-related errors."""


class EntityNotFoundException(RepositoryError):
    def __init__(self, entity_name: str, entity_id: Any | None = None):
        message = f"{entity_name} not found."
        if entity_id is not None:
            message += f" (ID: {entity_id})"
        super().__init__(message)


class RepositoryException(RepositoryError):
    def __init__(self, message: str = "An error occurred in the repository."):
        super().__init__(message)


class DuplicateEntryError(RepositoryError):
    def __init__(self, entity_name: str, conflicting_field: str, conflicting_value: Any):
        message = (
            f"Failed to create {entity_name}. "
            f"An entry with the value '{conflicting_value}' already exists "
            f"for field '{conflicting_field}'."
        )
        super().__init__(message)


class ForeignKeyViolationError(RepositoryError):
    def __init__(self, message: str = "A related entity does not exist."):
        super().__init__(message)
