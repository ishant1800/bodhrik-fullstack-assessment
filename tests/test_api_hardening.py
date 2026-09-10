"""Comprehensive test suite for Step 9: API Hardening & Production Readiness."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    BadRequestError,
    BookingConflictError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.booking import Booking
from app.models.enums import NotificationType, UserRole
from app.models.user import User
from app.services.notification_service import create_notification

# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db() -> Session:
    """Provide a database session for test assertions and cleanup."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def cleanup_hardening_test_data() -> None:
    """Ensure any test records created for hardening tests are purged."""
    yield
    session = SessionLocal()
    try:
        users = (
            session.execute(
                select(User).where(User.email.like("%@hardeningtest.example.com"))
            )
            .scalars()
            .all()
        )
        for u in users:
            # Delete bookings where user is participant
            bookings = (
                session.execute(
                    select(Booking).where(
                        (Booking.customer_id == u.id) | (Booking.provider_id == u.id)
                    )
                )
                .scalars()
                .all()
            )
            for b in bookings:
                session.delete(b)
            session.delete(u)
        session.commit()
    finally:
        session.close()


def create_user(
    db: Session,
    role: UserRole = UserRole.CUSTOMER,
    prefix: str = "user",
) -> tuple[User, str]:
    """Helper to create a user and signed Bearer token."""
    unique_suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}_{unique_suffix}@hardeningtest.example.com"
    user = User(
        name=f"Hardening {prefix.capitalize()} {unique_suffix}",
        email=email,
        password_hash=hash_password("Password123!"),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(subject=str(user.id))
    return user, f"Bearer {token}"


# ===========================================================================
# 1. Health Probe (Liveness) Tests
# ===========================================================================


def test_health_probe_liveness_root(client: TestClient) -> None:
    """Verify GET /health returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


def test_health_probe_liveness_v1(client: TestClient) -> None:
    """Verify GET /api/v1/health returns 200 with status ok."""
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


def test_health_probe_independent_from_database(client: TestClient) -> None:
    """Verify /health remains 200 ok even when database connectivity fails."""
    with patch("app.api.v1.health.check_db_connection", return_value=False):
        response = client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}


# ===========================================================================
# 2. Readiness Probe Tests
# ===========================================================================


def test_readiness_probe_healthy_db(client: TestClient) -> None:
    """Verify GET /ready and /api/v1/ready return 200 ready when DB is connected."""
    res_root = client.get("/ready")
    assert res_root.status_code == status.HTTP_200_OK
    assert res_root.json() == {"status": "ready"}

    res_v1 = client.get("/api/v1/ready")
    assert res_v1.status_code == status.HTTP_200_OK
    assert res_v1.json() == {"status": "ready"}


def test_readiness_probe_database_unavailable(client: TestClient) -> None:
    """Verify GET /ready returns 503 not_ready when database connectivity fails."""
    with patch("app.api.v1.health.check_db_connection", return_value=False):
        response = client.get("/ready")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"status": "not_ready"}


def test_readiness_probe_exception_safety_no_leaks(client: TestClient) -> None:
    """Verify /ready handles unexpected DB exceptions without leaking credentials."""
    sensitive_error = "postgres://user:secret_pass@10.0.0.1:5432/bodhrik fatal error"
    with patch(
        "app.api.v1.health.check_db_connection",
        side_effect=RuntimeError(sensitive_error),
    ):
        response = client.get("/ready")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"status": "not_ready"}
        # Ensure no secrets or connection strings are present in response text
        assert "secret_pass" not in response.text
        assert "10.0.0.1" not in response.text
        assert "postgres://" not in response.text


# ===========================================================================
# 3. Application Exception System Tests
# ===========================================================================


def test_app_exception_hierarchy() -> None:
    """Verify AppException and its subclasses have proper default codes and statuses."""
    exc = AppException("Base error", code="CUSTOM_CODE", status_code=502)
    assert exc.status_code == 502
    assert exc.code == "CUSTOM_CODE"
    assert exc.message == "Base error"

    nf = NotFoundError("Item not found")
    assert nf.status_code == 404
    assert nf.code == "NOT_FOUND"
    assert nf.message == "Item not found"

    fb = ForbiddenError("Access denied")
    assert fb.status_code == 403
    assert fb.code == "FORBIDDEN"
    assert fb.message == "Access denied"

    cf = ConflictError("Resource conflict")
    assert cf.status_code == 409
    assert cf.code == "CONFLICT"
    assert cf.message == "Resource conflict"

    br = BadRequestError("Invalid input")
    assert br.status_code == 400
    assert br.code == "BAD_REQUEST"
    assert br.message == "Invalid input"

    ua = UnauthorizedError("Missing token")
    assert ua.status_code == 401
    assert ua.code == "UNAUTHORIZED"
    assert ua.message == "Missing token"

    bc = BookingConflictError("Overlapping slot")
    assert bc.status_code == 409
    assert bc.code == "BOOKING_CONFLICT"
    assert bc.message == "Overlapping slot"


# ===========================================================================
# 4. Centralized Error Responses (400, 401, 403, 404, 409, 422, 500)
# ===========================================================================


def test_error_response_format_400(client: TestClient, db: Session) -> None:
    """Verify 400 Bad Request error response has consistent structure."""
    customer, token = create_user(db, UserRole.CUSTOMER, prefix="cust400")
    # Attempt to book self as provider -> 400
    response = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(customer.id),
            "service_name": "Self Service",
            "start_time": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "end_time": (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat(),
        },
        headers={"Authorization": token},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["code"] == "BAD_REQUEST"
    assert "Customer cannot book themselves" in data["message"]
    assert "Customer cannot book themselves" in str(data["detail"])


def test_error_response_format_401(client: TestClient) -> None:
    """Verify 401 Unauthorized returns code UNAUTHORIZED with message and detail."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent@hardeningtest.example.com",
            "password": "WrongPassword!",
        },
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert data["code"] == "UNAUTHORIZED"
    assert data["message"] == "Invalid email or password"
    assert data["detail"] == "Invalid email or password"


def test_error_response_format_403(client: TestClient, db: Session) -> None:
    """Verify 403 Forbidden returns code FORBIDDEN when user lacks required role."""
    _, cust_token = create_user(db, UserRole.CUSTOMER, prefix="cust403")
    # Notification belonging to another user
    other_user, _ = create_user(db, UserRole.CUSTOMER, prefix="other403")

    notif = create_notification(
        db=db,
        user_id=other_user.id,
        type=NotificationType.BOOKING_CONFIRMED,
        title="Other Notif",
        message="Message",
    )
    assert notif is not None
    db.commit()

    resp_forbidden = client.patch(
        f"/api/v1/notifications/{notif.id}/read",
        headers={"Authorization": cust_token},
    )
    assert resp_forbidden.status_code == status.HTTP_403_FORBIDDEN
    data = resp_forbidden.json()
    assert data["code"] == "FORBIDDEN"
    assert "Not authorized" in data["message"]
    assert "Not authorized" in str(data["detail"])


def test_error_response_format_404(client: TestClient, db: Session) -> None:
    """Verify 404 Not Found returns code NOT_FOUND."""
    _, token = create_user(db, UserRole.ADMIN, prefix="admin404")
    nonexistent_id = str(uuid.uuid4())
    response = client.get(
        f"/api/v1/bookings/{nonexistent_id}",
        headers={"Authorization": token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["code"] == "NOT_FOUND"
    assert data["message"] == "Booking not found"
    assert data["detail"] == "Booking not found"


def test_error_response_format_409(client: TestClient, db: Session) -> None:
    """Verify 409 Conflict returns code CONFLICT when duplicate registration occurs."""
    user, _ = create_user(db, UserRole.CUSTOMER, prefix="dup409")
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Duplicate User",
            "email": user.email,
            "password": "Password123!",
        },
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    data = response.json()
    assert data["code"] == "CONFLICT"
    assert "already exists" in data["message"]
    assert "already exists" in str(data["detail"])


def test_error_response_format_422_validation(client: TestClient) -> None:
    """Verify 422 validation failure produces code VALIDATION_ERROR with field list."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "",  # min_length 1 violated
            "email": "invalid-email-no-at",
            "password": "short",  # min_length 8 violated
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    data = response.json()
    assert data["code"] == "VALIDATION_ERROR"
    assert data["message"] == "Request validation failed."
    assert isinstance(data["detail"], list)
    assert len(data["detail"]) >= 1

    fields = [item["field"] for item in data["detail"]]
    assert any("email" in f or "password" in f or "name" in f for f in fields)
    for item in data["detail"]:
        assert "field" in item
        assert "message" in item
        # Ensure 'Value error, ' prefix is stripped if present
        assert not item["message"].startswith("Value error, ")


def test_unhandled_500_error_response_format(client: TestClient) -> None:
    """Verify unhandled 500 error returns safe shape without leaking internals."""
    original_setting = client._transport.raise_server_exceptions
    client._transport.raise_server_exceptions = False
    try:
        with patch(
            "app.services.auth_service.get_user_by_email",
            side_effect=RuntimeError(
                "CRITICAL: DB crash at /etc/secrets/db_creds.env on line 42"
            ),
        ):
            response = client.post(
                "/api/v1/auth/login",
                json={
                    "email": "anyuser@hardeningtest.example.com",
                    "password": "Password123!",
                },
            )
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            data = response.json()
            assert data["code"] == "INTERNAL_SERVER_ERROR"
            assert data["message"] == "An internal server error occurred."
            assert data["detail"] is None
            # Verify security: no tracebacks, file paths, or internal crash details
            assert "CRITICAL" not in response.text
            assert "secrets" not in response.text
            assert "db_creds" not in response.text
            assert "Traceback" not in response.text
    finally:
        client._transport.raise_server_exceptions = original_setting


# ===========================================================================
# 5. Security Headers & CORS Tests
# ===========================================================================


def test_security_headers_present_on_responses(client: TestClient) -> None:
    """Verify security hardening headers are injected on all HTTP responses."""
    endpoints = ["/health", "/ready", "/api/v1/health"]
    for ep in endpoints:
        response = client.get(ep)
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"
        assert response.headers.get("referrer-policy") == "no-referrer"


def test_cors_allowed_vite_and_localhost_origins(client: TestClient) -> None:
    """Verify configured development origins (including Vite 5173) are allowed."""
    for origin in [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]:
        response = client.get(
            "/health",
            headers={"Origin": origin},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.headers.get("access-control-allow-origin") == origin
        assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_disallows_unauthorized_origin(client: TestClient) -> None:
    """Verify arbitrary origins do not receive CORS authorization headers."""
    response = client.get(
        "/health",
        headers={"Origin": "https://malicious-attacker.com"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert "access-control-allow-origin" not in response.headers


# ===========================================================================
# 6. Pagination Consistency & Abuse Protection
# ===========================================================================


def test_pagination_boundary_rejection(client: TestClient, db: Session) -> None:
    """Verify invalid pagination values (skip < 0, limit <= 0, limit > 100) are 422."""
    _, token = create_user(db, UserRole.ADMIN, prefix="pageadmin")

    endpoints = [
        "/api/v1/bookings",
        "/api/v1/reviews",
        "/api/v1/providers",
        "/api/v1/notifications",
    ]

    for ep in endpoints:
        # Negative skip -> 422
        res_neg_skip = client.get(f"{ep}?skip=-1", headers={"Authorization": token})
        assert res_neg_skip.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert res_neg_skip.json()["code"] == "VALIDATION_ERROR"

        # Limit zero -> 422
        res_zero_limit = client.get(f"{ep}?limit=0", headers={"Authorization": token})
        assert res_zero_limit.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Limit > 100 -> 422
        res_high_limit = client.get(f"{ep}?limit=101", headers={"Authorization": token})
        assert res_high_limit.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Valid boundaries -> 200
        res_valid_min = client.get(
            f"{ep}?skip=0&limit=1", headers={"Authorization": token}
        )
        assert res_valid_min.status_code == status.HTTP_200_OK

        res_valid_max = client.get(
            f"{ep}?skip=0&limit=100", headers={"Authorization": token}
        )
        assert res_valid_max.status_code == status.HTTP_200_OK


def test_abuse_protection_login_field_lengths(client: TestClient) -> None:
    """Verify login input lengths are capped to prevent abusive bcrypt payloads."""
    # Email > 255 chars
    res_long_email = client.post(
        "/api/v1/auth/login",
        json={"email": "a" * 256 + "@example.com", "password": "password123"},
    )
    assert res_long_email.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Password > 128 chars
    res_long_pw = client.post(
        "/api/v1/auth/login",
        json={"email": "valid@example.com", "password": "p" * 129},
    )
    assert res_long_pw.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ===========================================================================
# 7. Authentication Token Hardening Review
# ===========================================================================


def test_authentication_missing_token(client: TestClient) -> None:
    """Verify request without Authorization header returns 401."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["code"] == "UNAUTHORIZED"


def test_authentication_malformed_token(client: TestClient) -> None:
    """Verify request with garbage token returns 401 without stack trace."""
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-valid-jwt-token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["code"] == "UNAUTHORIZED"


def test_authentication_expired_token(client: TestClient, db: Session) -> None:
    """Verify request with expired token returns 401."""
    user, _ = create_user(db, UserRole.CUSTOMER, prefix="expired")
    expired_token = create_access_token(
        subject=str(user.id),
        expires_delta=timedelta(minutes=-5),
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["code"] == "UNAUTHORIZED"


def test_authentication_nonexistent_user_token(client: TestClient) -> None:
    """Verify token signed for nonexistent UUID returns 401."""
    nonexistent_id = str(uuid.uuid4())
    token = create_access_token(subject=nonexistent_id)
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["code"] == "UNAUTHORIZED"


# ===========================================================================
# 8. OpenAPI Metadata & Documentation
# ===========================================================================


def test_openapi_documentation_metadata() -> None:
    """Verify OpenAPI schema generates valid title, version, and endpoints."""
    schema = app.openapi()
    assert schema["info"]["title"] == settings.PROJECT_NAME
    assert schema["info"]["version"] == "1.0.0"
    assert "/health" in schema["paths"]
    assert "/ready" in schema["paths"]
    assert "/api/v1/auth/login" in schema["paths"]
    assert "/api/v1/bookings" in schema["paths"]
    assert "/api/v1/providers" in schema["paths"]
    assert "/api/v1/reviews" in schema["paths"]
    assert "/api/v1/notifications" in schema["paths"]
