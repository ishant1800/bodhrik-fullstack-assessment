"""Health and readiness check endpoints."""

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.db.session import check_db_connection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", summary="Liveness check")
def health_check() -> dict[str, str]:
    """Liveness probe returning application status without external dependencies."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness check")
def readiness_check() -> JSONResponse:
    """Readiness probe verifying that required dependencies are available."""
    try:
        is_ready = check_db_connection()
    except Exception as exc:  # noqa: BLE001
        logger.error("Readiness check encountered an error: %s", exc)
        is_ready = False

    if is_ready:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ready"},
        )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "not_ready"},
    )
