import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import UserRole


class ProviderResponse(BaseModel):
    """Schema representing safe public profile information for a service provider."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: UserRole
    created_at: datetime
    updated_at: datetime


class ProviderAvailabilityResponse(BaseModel):
    """Schema representing provider availability determination for a time slot."""

    provider_id: uuid.UUID
    start_time: datetime = Field(..., description="Requested start timestamp")
    end_time: datetime = Field(..., description="Requested end timestamp")
    available: bool = Field(
        ..., description="Whether the provider is free during the requested time slot"
    )

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_timezone_aware(cls, v: datetime) -> datetime:
        """Validate that timestamps are timezone-aware."""
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("Datetime must be timezone-aware")
        return v

    @model_validator(mode="after")
    def validate_time_range(self) -> "ProviderAvailabilityResponse":
        """Enforce start_time < end_time."""
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self
