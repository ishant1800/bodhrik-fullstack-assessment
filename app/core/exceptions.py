"""Application-level domain exceptions with consistent error semantics."""

from typing import Any

from fastapi import status


class AppException(Exception):
    """Base application exception for consistent service-layer error semantics."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        detail: Any | None = None,
    ) -> None:
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.detail = detail
        super().__init__(self.message)


class NotFoundError(AppException):
    """Exception raised when a requested resource cannot be found."""

    status_code: int = status.HTTP_404_NOT_FOUND
    code: str = "NOT_FOUND"
    message: str = "Resource not found."


class ForbiddenError(AppException):
    """Exception raised when an authenticated user lacks permission for an action."""

    status_code: int = status.HTTP_403_FORBIDDEN
    code: str = "FORBIDDEN"
    message: str = "Forbidden."


class ConflictError(AppException):
    """Exception raised when an operation violates a business or state conflict."""

    status_code: int = status.HTTP_409_CONFLICT
    code: str = "CONFLICT"
    message: str = "Conflict."


class BadRequestError(AppException):
    """Exception raised when an invalid business request is submitted."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"
    message: str = "Bad request."


class UnauthorizedError(AppException):
    """Exception raised when authentication is missing or invalid."""

    status_code: int = status.HTTP_401_UNAUTHORIZED
    code: str = "UNAUTHORIZED"
    message: str = "Unauthorized."


class BookingConflictError(ConflictError):
    """Exception raised when a booking conflicts with provider availability."""

    status_code: int = status.HTTP_409_CONFLICT
    code: str = "BOOKING_CONFLICT"
    message: str = "Provider is not available during the requested time."
