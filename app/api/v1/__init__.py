"""API v1 package router."""

from fastapi import APIRouter

from app.api.v1.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="", tags=["health"])

__all__ = ["api_router"]
