"""
TestSphere-AI — Member 3 Service Layer Exceptions.

Decoupled domain and service-level exceptions.
Services do not import or raise FastAPI HTTPException directly.
"""


class ServiceError(Exception):
    """Base exception for all Member 3 service errors."""

    pass


class EntityNotFoundError(ServiceError):
    """Base exception for entity lookup failures."""

    pass


class ProjectNotFoundError(EntityNotFoundError):
    """Raised when a specified project cannot be found."""

    pass


class ApplicationNotFoundError(EntityNotFoundError):
    """Raised when a specified application cannot be found."""

    pass


class TestCaseNotFoundError(EntityNotFoundError):
    """Raised when a specified test case cannot be found."""

    pass


class TestExecutionNotFoundError(EntityNotFoundError):
    """Raised when a specified test execution cannot be found."""

    pass


class InvalidExecutionStatusError(ServiceError):
    """Raised when an invalid execution status is provided."""

    pass
