"""API v1 package router."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.health import router as health_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.providers import router as providers_router
from app.api.v1.reviews import router as reviews_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="", tags=["Health"])
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(bookings_router, prefix="/bookings", tags=["Bookings"])
api_router.include_router(reviews_router, prefix="/reviews", tags=["Reviews"])
api_router.include_router(providers_router, prefix="/providers", tags=["Providers"])
api_router.include_router(
    notifications_router, prefix="/notifications", tags=["Notifications"]
)

__all__ = ["api_router"]
