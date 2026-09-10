from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings resolved from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Bodhrik Fullstack Assessment API"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False

    # PostgreSQL Infrastructure Configuration
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "bodhrik"
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/bodhrik"

    # Redis (placeholder for later milestone)
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT Security Configuration (secret must come from environment / .env)
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Background Jobs & Notifications Configuration
    BACKGROUND_JOBS_ENABLED: bool = True
    BOOKING_REMINDER_MINUTES: int = Field(default=30, ge=1)
    BACKGROUND_JOB_INTERVAL_MINUTES: int = Field(default=5, ge=1)

    # CORS Security Configuration
    CORS_ORIGINS: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: object) -> list[str] | object:
        """Parse comma-separated string or JSON list into list of origins."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                import json

                return json.loads(stripped)
            return [i.strip() for i in stripped.split(",") if i.strip()]
        if isinstance(v, (list, set, tuple)):
            return list(v)
        return v


settings = Settings()
