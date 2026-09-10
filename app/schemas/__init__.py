"""Pydantic request and response schemas."""

from app.schemas.auth import TokenResponse, UserLogin, UserRegister
from app.schemas.booking import BookingCreate, BookingResponse, BookingUpdate
from app.schemas.error import ErrorResponse, ValidationErrorDetail
from app.schemas.notification import MarkAllReadResponse, NotificationResponse
from app.schemas.provider import ProviderAvailabilityResponse, ProviderResponse
from app.schemas.review import (
    ProviderReviewSummary,
    ReviewCreate,
    ReviewResponse,
    ReviewUpdate,
)
from app.schemas.user import UserResponse

__all__ = [
    "BookingCreate",
    "BookingResponse",
    "BookingUpdate",
    "ErrorResponse",
    "MarkAllReadResponse",
    "NotificationResponse",
    "ProviderAvailabilityResponse",
    "ProviderResponse",
    "ProviderReviewSummary",
    "ReviewCreate",
    "ReviewResponse",
    "ReviewUpdate",
    "TokenResponse",
    "UserLogin",
    "UserRegister",
    "UserResponse",
    "ValidationErrorDetail",
]
