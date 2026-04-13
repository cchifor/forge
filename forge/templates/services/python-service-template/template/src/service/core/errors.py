class ApplicationError(Exception):
    """Base class for all application-specific errors."""

    @property
    def message(self):
        return self.args[0] if self.args else "An application error occurred."


class ServiceError(ApplicationError):
    """Base class for service layer errors."""


class ValidationError(ServiceError):
    """Raised when input data fails validation."""

    def __init__(self, message="Input data is invalid."):
        super().__init__(message)


class PermissionDeniedError(ServiceError):
    """Raised when a user attempts an action they are not authorized to perform."""

    def __init__(self, message="You do not have permission to perform this action."):
        super().__init__(message)
