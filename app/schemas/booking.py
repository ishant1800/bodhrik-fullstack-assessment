import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import BookingStatus


class BookingCreate(BaseModel):
    """Schema for creating a new booking request."""

    customer_id: uuid.UUID
    provider_id: uuid.UUID
    service_name: str
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def validate_booking_rules(self) -> "BookingCreate":
        """Enforce business rules for booking creation."""
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.customer_id == self.provider_id:
            raise ValueError("customer_id cannot be equal to provider_id")
        return self


class BookingUpdate(BaseModel):
    """Schema for updating an existing booking."""

    service_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: BookingStatus | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "BookingUpdate":
        """Enforce time range consistency if both are provided."""
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
