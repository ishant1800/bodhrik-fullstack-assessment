import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import BookingStatus


class BookingCreate(BaseModel):
    """Schema for creating a new booking request.

    Note: customer_id is inferred strictly from the authenticated user
    and must not be accepted in request payloads.
    """

    provider_id: uuid.UUID
    service_name: str = Field(
        ..., min_length=1, max_length=255, description="Name of the booked service"
    )
    start_time: datetime = Field(..., description="Service start timestamp")
    end_time: datetime = Field(..., description="Service end timestamp")

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_timezone_aware(cls, v: datetime) -> datetime:
        """Validate that timestamps are timezone-aware."""
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("Datetime must be timezone-aware")
        return v

    @model_validator(mode="after")
    def validate_booking_rules(self) -> "BookingCreate":
        """Enforce business rules for booking creation."""
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class BookingUpdate(BaseModel):
    """Schema for updating an existing booking.

    Ownership fields (customer_id, provider_id) are strictly immutable and omitted.
    """

    service_name: str | None = Field(
        default=None, min_length=1, max_length=255, description="Updated service name"
    )
    start_time: datetime | None = Field(
        default=None, description="Updated start timestamp"
    )
    end_time: datetime | None = Field(default=None, description="Updated end timestamp")
    status: BookingStatus | None = Field(
        default=None, description="Target booking status"
    )

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_timezone_aware(cls, v: datetime | None) -> datetime | None:
        """Validate that timestamps are timezone-aware if provided."""
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError("Datetime must be timezone-aware")
        return v

    @model_validator(mode="after")
    def validate_time_range(self) -> "BookingUpdate":
        """Enforce time range consistency if both start and end are provided."""
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be after start_time")
        return self


class BookingResponse(BaseModel):
    """Schema representing booking data returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    provider_id: uuid.UUID
    service_name: str
    start_time: datetime
    end_time: datetime
    status: BookingStatus
    created_at: datetime
    updated_at: datetime
