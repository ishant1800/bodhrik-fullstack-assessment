import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    """Schema for submitting a review for a completed booking.

    Note: customer_id and provider_id are strictly inferred from the
    authenticated user and referenced booking, and are omitted from client requests.
    """

    booking_id: uuid.UUID = Field(
        ..., description="UUID of completed booking to review"
    )
    rating: int = Field(..., ge=1, le=5, description="Rating score between 1 and 5")
    comment: str | None = Field(
        default=None, max_length=2000, description="Optional customer review comment"
    )


class ReviewUpdate(BaseModel):
    """Schema for updating an existing review.

    Only rating and comment may be modified. Ownership fields are strictly immutable.
    """

    rating: int | None = Field(
        default=None, ge=1, le=5, description="Updated rating score between 1 and 5"
    )
    comment: str | None = Field(
        default=None, max_length=2000, description="Updated customer review comment"
    )


class ReviewResponse(BaseModel):
    """Schema representing review data returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    booking_id: uuid.UUID
    customer_id: uuid.UUID
    provider_id: uuid.UUID
    rating: int
    comment: str | None
    created_at: datetime
    updated_at: datetime


class ProviderReviewSummary(BaseModel):
    """Schema representing aggregated review metrics for a service provider."""

    provider_id: uuid.UUID
    review_count: int = Field(..., ge=0, description="Total number of reviews")
    average_rating: float = Field(
        ..., ge=0.0, le=5.0, description="Average rating score"
    )
    rating_distribution: dict[str, int] = Field(
        ..., description="Count of reviews for each score from '1' to '5'"
    )
