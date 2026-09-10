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

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT Authentication (scaffolding for future step)
    JWT_SECRET: str = "super-secret-key-change-in-production-minimum-32-chars-length"
    JWT_ALGORITHM: str = "HS256"


settings = Settings()
