from pydantic import Field
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


settings = Settings()
