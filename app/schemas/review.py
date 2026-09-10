import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewCreate(BaseModel):
    """Schema for submitting a review for a completed booking."""

    booking_id: uuid.UUID
    customer_id: uuid.UUID
    provider_id: uuid.UUID
    rating: int = Field(..., ge=1, le=5, description="Rating score between 1 and 5")
    comment: str | None = None

    @model_validator(mode="after")
    def validate_review_parties(self) -> "ReviewCreate":
        """Ensure customer cannot review themselves as provider."""
        if self.customer_id == self.provider_id:
            raise ValueError("customer_id cannot be equal to provider_id")
        return self


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
