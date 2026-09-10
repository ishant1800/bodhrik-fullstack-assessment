from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.jobs.scheduler import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle events."""
    if settings.BACKGROUND_JOBS_ENABLED:
        scheduler.start()
    try:
        yield
    finally:
        if settings.BACKGROUND_JOBS_ENABLED:
            await scheduler.stop()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Root-level health check endpoint: GET /health
app.include_router(health_router)

# Versioned API router: GET /api/v1/*
app.include_router(api_router, prefix=settings.API_V1_STR)
