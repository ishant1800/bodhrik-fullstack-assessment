from pydantic import BaseModel, Field, field_validator


class UserRegister(BaseModel):
    """Schema for user registration."""

    name: str = Field(..., min_length=1, max_length=255, description="User full name")
    email: str = Field(..., min_length=3, max_length=255, description="Email address")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password with at least 8 characters",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email address by trimming whitespace and lowercasing."""
        normalized = v.strip().lower()
        if "@" not in normalized or "." not in normalized.split("@")[-1]:
            raise ValueError("Invalid email address format")
        return normalized


class UserLogin(BaseModel):
    """Schema for user login credentials."""

    email: str = Field(..., max_length=255, description="Registered email address")
    password: str = Field(..., max_length=128, description="Password")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email address for lookup."""
        return v.strip().lower()


class TokenResponse(BaseModel):
    """Schema for JWT token response."""

    access_token: str
    token_type: str = "bearer"
