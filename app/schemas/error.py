"""Error response schemas for centralized exception handling."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ValidationErrorDetail(BaseModel):
    """Schema for individual field validation error."""

    model_config = ConfigDict(from_attributes=True)

    field: str = Field(..., description="Target field name or location")
    message: str = Field(..., description="Field validation error description")


class ErrorResponse(BaseModel):
    """Standardized error response shape across the entire API."""

    model_config = ConfigDict(from_attributes=True)

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    detail: Any | None = Field(
        default=None,
        description="Optional detailed error context or list of field errors",
    )
