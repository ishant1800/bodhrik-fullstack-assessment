import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewSummaryJobRequest(BaseModel):
    """Payload to trigger an asynchronous review summarisation job."""

    provider_id: uuid.UUID = Field(
        ...,
        description="UUID of the service provider whose reviews should be summarized",
    )


class ReviewSummaryResult(BaseModel):
    """Deterministic review summarisation metrics and text."""

    model_config = ConfigDict(from_attributes=True)

    provider_id: uuid.UUID = Field(..., description="Provider UUID")
    provider_name: str = Field(..., description="Name of the service provider")
    review_count: int = Field(..., ge=0, description="Total number of reviews")
    average_rating: float = Field(
        ..., ge=0.0, le=5.0, description="Average rating score"
    )
    rating_distribution: dict[str, int] = Field(
        ..., description="Count of reviews per rating bucket (1 to 5)"
    )
    summary: str = Field(..., description="Deterministic natural language summary")
    generated_at: datetime = Field(
        ..., description="Timestamp when the summary was generated"
    )


class ReviewSummaryJobResponse(BaseModel):
    """Response representing the asynchronous summarisation job status and result."""

    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID = Field(..., description="Unique task identifier")
    status: Literal["queued", "processing", "completed", "failed"] = Field(
        ..., description="Current execution status of the job"
    )
    provider_id: uuid.UUID = Field(..., description="Target service provider UUID")
    result: ReviewSummaryResult | None = Field(
        default=None,
        description="Completed summary result (available when status is completed)",
    )
    error: str | None = Field(
        default=None,
        description="Failure reason if the job failed",
    )
    created_at: datetime = Field(..., description="Job enqueue timestamp")
    updated_at: datetime | None = Field(
        default=None, description="Last status update timestamp"
    )
