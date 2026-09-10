import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.core.exceptions import AppException
from app.jobs.scheduler import scheduler

logger = logging.getLogger(__name__)


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
    description="Production-ready REST API for the Bodhrik Service Booking Platform.",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Security & Hardening Middleware
# ---------------------------------------------------------------------------

# CORS configuration restricted to configured development and production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityHeadersMiddleware:
    """Pure ASGI middleware injecting standard security hardening headers."""

    def __init__(self, app_instance: ASGIApp) -> None:
        self.app = app_instance

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers: list[tuple[bytes, bytes]] = list(
                    message.get("headers", [])
                )
                header_names = {h[0].lower() for h in raw_headers}
                if b"x-content-type-options" not in header_names:
                    raw_headers.append((b"x-content-type-options", b"nosniff"))
                if b"x-frame-options" not in header_names:
                    raw_headers.append((b"x-frame-options", b"DENY"))
                if b"referrer-policy" not in header_names:
                    raw_headers.append((b"referrer-policy", b"no-referrer"))
                message["headers"] = raw_headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


app.add_middleware(SecurityHeadersMiddleware)


# ---------------------------------------------------------------------------
# Centralized Exception Handlers
# ---------------------------------------------------------------------------


def _status_to_code(status_code: int) -> str:
    """Map common HTTP status codes to machine-readable error codes."""
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    return mapping.get(status_code, f"HTTP_{status_code}")


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle custom application domain exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI/Pydantic request validation failures."""
    formatted_errors: list[dict[str, str]] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        field_parts = [str(x) for x in loc if x not in ("body",)]
        field = ".".join(field_parts) if field_parts else "request"
        msg = err.get("msg", "Invalid value")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        formatted_errors.append({"field": field, "message": msg})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed.",
            "detail": formatted_errors,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle standard HTTP exceptions while preserving message and detail."""
    code = _status_to_code(exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else "An error occurred."
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "message": message,
            "detail": exc.detail,
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected server errors safely without leaking internal data."""
    logger.exception(
        "Unhandled server error processing %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An internal server error occurred.",
            "detail": None,
        },
    )


# ---------------------------------------------------------------------------
# Router Registration
# ---------------------------------------------------------------------------

# Root-level health & readiness endpoints: GET /health, GET /ready
app.include_router(health_router, tags=["Health"])

# Versioned API router: GET /api/v1/*
app.include_router(api_router, prefix=settings.API_V1_STR)
