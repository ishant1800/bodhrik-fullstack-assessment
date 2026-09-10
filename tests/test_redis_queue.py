"""Tests for Redis connection foundation, client pooling, and review summarisation."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.redis import (
    check_redis_connection,
    close_redis_connection,
    get_redis_client,
    get_redis_pool,
)
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.review import Review
from app.models.user import User
from app.services.review_summary_service import QUEUE_NAME
from app.workers.review_worker import run_worker


@pytest.fixture
def db_session() -> Session:
    """Provide a scoped database session for testing."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_redis_queue() -> None:
    """Clear Redis task queue before and after each test."""
    try:
        client = get_redis_client()
        client.delete(QUEUE_NAME)
    except Exception:
        pass
    yield
    try:
        client = get_redis_client()
        client.delete(QUEUE_NAME)
    except Exception:
        pass


def _create_test_user(
    db: Session,
    role: UserRole = UserRole.CUSTOMER,
    prefix: str = "redis_user",
) -> tuple[User, str]:
    """Helper to create a user and signed Bearer token."""
    unique = uuid.uuid4().hex[:8]
    email = f"{prefix}_{unique}@example.com"
    user = User(
        name=f"Redis Test {prefix.capitalize()} {unique}",
        email=email,
        password_hash=hash_password("Password123!"),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(subject=str(user.id))
    return user, f"Bearer {token}"


def test_redis_connection_healthy() -> None:
    """Verify that Redis connection check succeeds when Redis is online."""
    assert check_redis_connection() is True


def test_redis_client_ping_and_operations() -> None:
    """Verify get_redis_client returns a working client for key-value ops."""
    client = get_redis_client()
    test_key = "test:probe_key"
    client.set(test_key, "hello_bodhrik", ex=10)
    val = client.get(test_key)
    assert val == "hello_bodhrik"
    client.delete(test_key)


def test_redis_pool_reuse_and_close() -> None:
    """Verify that connection pool is a reusable singleton and can be disconnected."""
    pool1 = get_redis_pool()
    pool2 = get_redis_pool()
    assert pool1 is pool2

    close_redis_connection()
    pool3 = get_redis_pool()
    assert pool3 is not None


def test_check_redis_connection_failure_safe() -> None:
    """Verify that check_redis_connection returns False and does not raise on error."""
    with patch("app.core.redis.get_redis_client") as mock_client:
        mock_client.return_value.ping.side_effect = Exception(
            "redis://user:secret@10.0.0.9:6379 Connection refused"
        )
        assert check_redis_connection() is False


def test_readiness_probe_redis_down(client: TestClient) -> None:
    """Verify GET /ready returns 503 not_ready when Redis is down but DB is healthy."""
    with patch("app.api.v1.health.check_redis_connection", return_value=False):
        response = client.get("/ready")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"status": "not_ready"}


def test_readiness_probe_redis_exception_safe_no_leaks(client: TestClient) -> None:
    """Verify GET /ready suppresses Redis exception details and never leaks URLs."""
    with patch(
        "app.api.v1.health.check_redis_connection",
        side_effect=RuntimeError("redis://:secret_token@127.0.0.1:6379/0 error"),
    ):
        response = client.get("/ready")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"status": "not_ready"}
        assert "secret_token" not in response.text


# ===========================================================================
# Review Summarisation API & Worker Tests
# ===========================================================================


def test_summarize_endpoint_unauthenticated_rejected(client: TestClient) -> None:
    """Verify POST /api/v1/reviews/summarize requires authentication."""
    response = client.post(
        "/api/v1/reviews/summarize",
        json={"provider_id": str(uuid.uuid4())},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["code"] == "UNAUTHORIZED"


def test_summarize_endpoint_nonexistent_provider(
    client: TestClient, db_session: Session
) -> None:
    """Verify POST /api/v1/reviews/summarize returns 404 for unknown provider."""
    _, token = _create_test_user(db_session, role=UserRole.CUSTOMER)
    response = client.post(
        "/api/v1/reviews/summarize",
        json={"provider_id": str(uuid.uuid4())},
        headers={"Authorization": token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["detail"] == "Provider not found"


def test_summarize_endpoint_non_provider_user(
    client: TestClient, db_session: Session
) -> None:
    """Verify POST /api/v1/reviews/summarize returns 400 if user is not a provider."""
    customer, token = _create_test_user(db_session, role=UserRole.CUSTOMER)
    response = client.post(
        "/api/v1/reviews/summarize",
        json={"provider_id": str(customer.id)},
        headers={"Authorization": token},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "BAD_REQUEST"
    assert "not registered as a service provider" in response.json()["detail"]


def test_summarize_endpoint_enqueues_successfully(
    client: TestClient, db_session: Session
) -> None:
    """Verify POST /api/v1/reviews/summarize returns 202 and enqueues job in Redis."""
    provider, _ = _create_test_user(db_session, role=UserRole.PROVIDER, prefix="prov")
    customer, token = _create_test_user(
        db_session, role=UserRole.CUSTOMER, prefix="cust"
    )

    response = client.post(
        "/api/v1/reviews/summarize",
        json={"provider_id": str(provider.id)},
        headers={"Authorization": token},
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    body = response.json()
    assert body["status"] == "queued"
    assert body["provider_id"] == str(provider.id)
    assert "job_id" in body

    # Verify job exists in Redis
    job_id = body["job_id"]
    get_res = client.get(
        f"/api/v1/reviews/summarize/{job_id}",
        headers={"Authorization": token},
    )
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["status"] == "queued"
    assert get_res.json()["result"] is None


def test_get_summarize_job_nonexistent(client: TestClient, db_session: Session) -> None:
    """Verify GET /api/v1/reviews/summarize/{job_id} returns 404 for unknown job."""
    _, token = _create_test_user(db_session, role=UserRole.CUSTOMER)
    random_job_id = uuid.uuid4()
    response = client.get(
        f"/api/v1/reviews/summarize/{random_job_id}",
        headers={"Authorization": token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "NOT_FOUND"


def test_worker_processes_summary_job_end_to_end(
    client: TestClient, db_session: Session
) -> None:
    """Verify worker consumes task from Redis, calculates metrics, and completes job."""
    provider, _ = _create_test_user(db_session, role=UserRole.PROVIDER, prefix="doc")
    customer1, token1 = _create_test_user(
        db_session, role=UserRole.CUSTOMER, prefix="c1"
    )
    customer2, _ = _create_test_user(db_session, role=UserRole.CUSTOMER, prefix="c2")

    # Create completed bookings and reviews
    now = datetime.now(UTC)
    b1 = Booking(
        customer_id=customer1.id,
        provider_id=provider.id,
        service_name="Consultation 1",
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=2, hours=-1),
        status=BookingStatus.COMPLETED,
    )
    b2 = Booking(
        customer_id=customer2.id,
        provider_id=provider.id,
        service_name="Consultation 2",
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(days=1, hours=-1),
        status=BookingStatus.COMPLETED,
    )
    db_session.add_all([b1, b2])
    db_session.commit()

    r1 = Review(
        booking_id=b1.id,
        customer_id=customer1.id,
        provider_id=provider.id,
        rating=5,
        comment="Outstanding care and attention to detail.",
    )
    r2 = Review(
        booking_id=b2.id,
        customer_id=customer2.id,
        provider_id=provider.id,
        rating=4,
        comment="Very helpful consultation.",
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    # Trigger summarisation
    post_res = client.post(
        "/api/v1/reviews/summarize",
        json={"provider_id": str(provider.id)},
        headers={"Authorization": token1},
    )
    assert post_res.status_code == status.HTTP_202_ACCEPTED
    job_id = post_res.json()["job_id"]

    # Run the worker for 1 job
    processed = run_worker(poll_timeout=1, max_jobs=1)
    assert processed == 1

    # Check status via API
    get_res = client.get(
        f"/api/v1/reviews/summarize/{job_id}",
        headers={"Authorization": token1},
    )
    assert get_res.status_code == status.HTTP_200_OK
    data = get_res.json()
    assert data["status"] == "completed"
    assert data["result"] is not None

    result = data["result"]
    assert result["provider_id"] == str(provider.id)
    assert result["provider_name"] == provider.name
    assert result["review_count"] == 2
    assert result["average_rating"] == 4.5
    assert result["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1}
    assert provider.name in result["summary"]
    assert "overwhelmingly positive" in result["summary"]


def test_worker_processes_provider_with_zero_reviews(
    client: TestClient, db_session: Session
) -> None:
    """Verify worker generates clean summary for a provider with 0 reviews."""
    provider, _ = _create_test_user(
        db_session, role=UserRole.PROVIDER, prefix="zerorev"
    )
    _, token = _create_test_user(db_session, role=UserRole.ADMIN, prefix="admin")

    post_res = client.post(
        "/api/v1/reviews/summarize",
        json={"provider_id": str(provider.id)},
        headers={"Authorization": token},
    )
    assert post_res.status_code == status.HTTP_202_ACCEPTED
    job_id = post_res.json()["job_id"]

    processed = run_worker(poll_timeout=1, max_jobs=1)
    assert processed == 1

    get_res = client.get(
        f"/api/v1/reviews/summarize/{job_id}",
        headers={"Authorization": token},
    )
    assert get_res.status_code == status.HTTP_200_OK
    data = get_res.json()
    assert data["status"] == "completed"
    assert data["result"]["review_count"] == 0
    assert data["result"]["average_rating"] == 0.0
    assert "no customer reviews yet" in data["result"]["summary"]


def test_summarize_endpoint_redis_offline_returns_503(
    client: TestClient, db_session: Session
) -> None:
    """Verify POST /api/v1/reviews/summarize returns 503 if Redis is unreachable."""
    provider, _ = _create_test_user(db_session, role=UserRole.PROVIDER, prefix="p503")
    _, token = _create_test_user(db_session, role=UserRole.CUSTOMER, prefix="c503")

    with patch("app.services.review_summary_service.get_redis_client") as mock_redis:
        mock_redis.side_effect = RuntimeError("Redis connection down")
        response = client.post(
            "/api/v1/reviews/summarize",
            json={"provider_id": str(provider.id)},
            headers={"Authorization": token},
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["code"] == "SERVICE_UNAVAILABLE"


def test_get_summarize_job_redis_offline_returns_503(
    client: TestClient, db_session: Session
) -> None:
    """Verify GET /summarize/{job_id} returns 503 if Redis is unreachable."""
    _, token = _create_test_user(db_session, role=UserRole.CUSTOMER)
    with patch("app.services.review_summary_service.get_redis_client") as mock_redis:
        mock_redis.side_effect = RuntimeError("Redis connection down")
        response = client.get(
            f"/api/v1/reviews/summarize/{uuid.uuid4()}",
            headers={"Authorization": token},
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["code"] == "SERVICE_UNAVAILABLE"


def test_summarize_rbac_allowed_for_all_authenticated_roles(
    client: TestClient, db_session: Session
) -> None:
    """Verify Customer, Provider, and Admin roles can trigger review summarisation."""
    provider, _ = _create_test_user(db_session, role=UserRole.PROVIDER, prefix="target")
    _, cust_token = _create_test_user(db_session, role=UserRole.CUSTOMER, prefix="c")
    _, prov_token = _create_test_user(db_session, role=UserRole.PROVIDER, prefix="p")
    _, admin_token = _create_test_user(db_session, role=UserRole.ADMIN, prefix="a")

    for token in (cust_token, prov_token, admin_token):
        res = client.post(
            "/api/v1/reviews/summarize",
            json={"provider_id": str(provider.id)},
            headers={"Authorization": token},
        )
        assert res.status_code == status.HTTP_202_ACCEPTED
        assert res.json()["status"] == "queued"
