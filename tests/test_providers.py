import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.user import User

# ---------------------------------------------------------------------------
# Test Setup & Cleanup Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db() -> Session:
    """Yield a database session for test assertions and setup."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def cleanup_provider_test_data():
    """Clean up test bookings and users after each test."""
    yield
    session = SessionLocal()
    try:
        # Delete test bookings first
        bookings = (
            session.execute(
                select(Booking).where(Booking.service_name.like("TestProvider%"))
            )
            .scalars()
            .all()
        )
        for b in bookings:
            session.delete(b)
        session.commit()

        # Delete test users
        users = (
            session.execute(
                select(User).where(User.email.like("%@providertest.example.com"))
            )
            .scalars()
            .all()
        )
        for u in users:
            session.delete(u)
        session.commit()
    finally:
        session.close()


def create_user_with_token(
    db: Session,
    role: UserRole,
    name: str = "Test User",
) -> tuple[User, str]:
    """Helper creating a test user and returning user record and Bearer auth header."""
    user = User(
        name=name,
        email=f"{role.value}_{uuid.uuid4().hex[:8]}@providertest.example.com",
        password_hash=hash_password("Password123!"),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(subject=str(user.id))
    return user, f"Bearer {token}"


def create_test_booking(
    db: Session,
    customer: User,
    provider: User,
    start_time: datetime,
    end_time: datetime,
    booking_status: BookingStatus = BookingStatus.PENDING,
    service_name: str = "TestProvider Service",
) -> Booking:
    """Helper creating a booking reservation with specified times and state."""
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name=service_name,
        start_time=start_time,
        end_time=end_time,
        status=booking_status,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


# ===========================================================================
# 1. Authentication Tests
# ===========================================================================


def test_unauthenticated_requests_rejected(client: TestClient) -> None:
    """Verify provider endpoints reject unauthenticated requests with 401."""
    fake_id = str(uuid.uuid4())
    start = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    end = (datetime.now(UTC) + timedelta(days=1, hours=2)).isoformat()

    assert client.get("/api/v1/providers").status_code == status.HTTP_401_UNAUTHORIZED
    assert (
        client.get(f"/api/v1/providers/{fake_id}").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.get(
            f"/api/v1/providers/{fake_id}/availability",
            params={"start_time": start, "end_time": end},
        ).status_code
        == status.HTTP_401_UNAUTHORIZED
    )


# ===========================================================================
# 2. Provider Listing Tests
# ===========================================================================


def test_list_providers_role_access_and_filtering(
    client: TestClient, db: Session
) -> None:
    """Verify all roles can list providers, and only PROVIDER users appear."""
    customer, cust_token = create_user_with_token(
        db, UserRole.CUSTOMER, name="Alice Customer"
    )
    provider1, prov_token = create_user_with_token(
        db, UserRole.PROVIDER, name="Dr. Bob Provider"
    )
    provider2, _ = create_user_with_token(
        db, UserRole.PROVIDER, name="Dr. Charlie Provider"
    )
    admin, admin_token = create_user_with_token(db, UserRole.ADMIN, name="Dave Admin")

    # Customer can list providers
    res_cust = client.get("/api/v1/providers", headers={"Authorization": cust_token})
    assert res_cust.status_code == status.HTTP_200_OK
    cust_data = res_cust.json()
    assert len(cust_data) >= 2
    assert all(p["role"] == "provider" for p in cust_data)
    assert not any(p["id"] == str(customer.id) for p in cust_data)
    assert not any(p["id"] == str(admin.id) for p in cust_data)
    assert any(p["id"] == str(provider1.id) for p in cust_data)
    assert any(p["id"] == str(provider2.id) for p in cust_data)

    # Provider can list providers
    res_prov = client.get("/api/v1/providers", headers={"Authorization": prov_token})
    assert res_prov.status_code == status.HTTP_200_OK

    # Admin can list providers
    res_admin = client.get("/api/v1/providers", headers={"Authorization": admin_token})
    assert res_admin.status_code == status.HTTP_200_OK

    # Verify password_hash is never exposed in the response
    for item in cust_data:
        assert "password_hash" not in item
        assert "password" not in item


def test_list_providers_pagination_and_search(client: TestClient, db: Session) -> None:
    """Verify pagination bounds and search filtering work accurately."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    p1, _ = create_user_with_token(db, UserRole.PROVIDER, name="UniqueAlpha Service")
    p2, _ = create_user_with_token(db, UserRole.PROVIDER, name="UniqueBeta Service")

    # Search by name
    res_search = client.get(
        "/api/v1/providers?search=UniqueAlpha",
        headers={"Authorization": cust_token},
    )
    assert res_search.status_code == status.HTTP_200_OK
    search_data = res_search.json()
    assert len(search_data) == 1
    assert search_data[0]["id"] == str(p1.id)

    # Search by email
    res_email = client.get(
        f"/api/v1/providers?search={p2.email}",
        headers={"Authorization": cust_token},
    )
    assert res_email.status_code == status.HTTP_200_OK
    email_data = res_email.json()
    assert len(email_data) == 1
    assert email_data[0]["id"] == str(p2.id)

    # Pagination: limit 1
    res_page = client.get(
        "/api/v1/providers?limit=1&skip=0",
        headers={"Authorization": cust_token},
    )
    assert res_page.status_code == status.HTTP_200_OK
    assert len(res_page.json()) == 1


# ===========================================================================
# 3. Provider Details Tests
# ===========================================================================


def test_get_provider_by_id_success(client: TestClient, db: Session) -> None:
    """Verify retrieving an existing provider returns safe public profile."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER, name="Safe Provider")

    response = client.get(
        f"/api/v1/providers/{provider.id}",
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == str(provider.id)
    assert data["name"] == "Safe Provider"
    assert data["email"] == provider.email
    assert data["role"] == "provider"
    assert "created_at" in data
    assert "updated_at" in data
    assert "password_hash" not in data


def test_get_provider_by_id_nonexistent(client: TestClient, db: Session) -> None:
    """Verify 404 Not Found when provider ID does not exist."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    fake_id = str(uuid.uuid4())

    response = client.get(
        f"/api/v1/providers/{fake_id}",
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Provider not found" in response.json()["detail"]


def test_get_provider_by_id_non_provider_roles(client: TestClient, db: Session) -> None:
    """Verify 400 Bad Request when requested ID is a customer or admin."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    admin, _ = create_user_with_token(db, UserRole.ADMIN)

    # Requesting customer ID as provider
    res_cust = client.get(
        f"/api/v1/providers/{customer.id}",
        headers={"Authorization": cust_token},
    )
    assert res_cust.status_code == status.HTTP_400_BAD_REQUEST
    assert "not registered as a service provider" in res_cust.json()["detail"]

    # Requesting admin ID as provider
    res_admin = client.get(
        f"/api/v1/providers/{admin.id}",
        headers={"Authorization": cust_token},
    )
    assert res_admin.status_code == status.HTTP_400_BAD_REQUEST
    assert "not registered as a service provider" in res_admin.json()["detail"]


def test_get_provider_malformed_uuid(client: TestClient, db: Session) -> None:
    """Verify 422 Unprocessable Entity for invalid UUID format."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)

    response = client.get(
        "/api/v1/providers/not-a-uuid",
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ===========================================================================
# 4. Provider Availability Tests
# ===========================================================================


def test_check_provider_availability_empty_slot(
    client: TestClient, db: Session
) -> None:
    """Verify provider with no bookings is available."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=5, hours=10)
    end = start + timedelta(hours=2)

    response = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["provider_id"] == str(provider.id)
    assert data["available"] is True


@pytest.mark.parametrize(
    "blocking_status",
    [BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED],
)
def test_check_provider_availability_blocking_statuses(
    client: TestClient, db: Session, blocking_status: BookingStatus
) -> None:
    """Verify PENDING, CONFIRMED, and COMPLETED bookings block availability."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=6, hours=10)
    end = start + timedelta(hours=2)

    create_test_booking(
        db,
        customer,
        provider,
        start_time=start,
        end_time=end,
        booking_status=blocking_status,
    )

    response = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["provider_id"] == str(provider.id)
    assert data["available"] is False


def test_check_provider_availability_cancelled_does_not_block(
    client: TestClient, db: Session
) -> None:
    """Verify CANCELLED bookings do not block availability."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=7, hours=10)
    end = start + timedelta(hours=2)

    create_test_booking(
        db,
        customer,
        provider,
        start_time=start,
        end_time=end,
        booking_status=BookingStatus.CANCELLED,
    )

    response = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["available"] is True


def test_check_provider_availability_adjacent_slots_allowed(
    client: TestClient, db: Session
) -> None:
    """Verify back-to-back adjacent bookings are permitted and available."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    existing_start = datetime.now(UTC) + timedelta(days=8, hours=10)
    existing_end = existing_start + timedelta(hours=2)

    create_test_booking(
        db,
        customer,
        provider,
        start_time=existing_start,
        end_time=existing_end,
        booking_status=BookingStatus.CONFIRMED,
    )

    # Immediately preceding slot (end == existing.start)
    prior_start = existing_start - timedelta(hours=2)
    prior_end = existing_start
    res_prior = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={
            "start_time": prior_start.isoformat(),
            "end_time": prior_end.isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res_prior.status_code == status.HTTP_200_OK
    assert res_prior.json()["available"] is True

    # Immediately succeeding slot (start == existing.end)
    after_start = existing_end
    after_end = existing_end + timedelta(hours=2)
    res_after = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={
            "start_time": after_start.isoformat(),
            "end_time": after_end.isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res_after.status_code == status.HTTP_200_OK
    assert res_after.json()["available"] is True


def test_check_provider_availability_overlap_scenarios(
    client: TestClient, db: Session
) -> None:
    """Verify all partial and complete overlap scenarios return available=false."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    # Existing booking: 10:00 -> 12:00
    base = datetime.now(UTC) + timedelta(days=9)
    b_start = base.replace(hour=10, minute=0, second=0, microsecond=0)
    b_end = base.replace(hour=12, minute=0, second=0, microsecond=0)

    create_test_booking(
        db,
        customer,
        provider,
        start_time=b_start,
        end_time=b_end,
        booking_status=BookingStatus.CONFIRMED,
    )

    # 1. Partial overlap at beginning: 09:30 -> 10:30
    res1 = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={
            "start_time": (b_start - timedelta(minutes=30)).isoformat(),
            "end_time": (b_start + timedelta(minutes=30)).isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res1.status_code == status.HTTP_200_OK
    assert res1.json()["available"] is False

    # 2. Partial overlap at end: 11:30 -> 12:30
    res2 = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={
            "start_time": (b_end - timedelta(minutes=30)).isoformat(),
            "end_time": (b_end + timedelta(minutes=30)).isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["available"] is False

    # 3. Completely enclosing: 09:00 -> 13:00
    res3 = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={
            "start_time": (b_start - timedelta(hours=1)).isoformat(),
            "end_time": (b_end + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res3.status_code == status.HTTP_200_OK
    assert res3.json()["available"] is False

    # 4. Completely enclosed inside: 10:30 -> 11:30
    res4 = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={
            "start_time": (b_start + timedelta(minutes=30)).isoformat(),
            "end_time": (b_end - timedelta(minutes=30)).isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res4.status_code == status.HTTP_200_OK
    assert res4.json()["available"] is False


def test_check_provider_availability_validation_errors(
    client: TestClient, db: Session
) -> None:
    """Verify availability errors for invalid inputs and missing providers."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    valid_start = (datetime.now(UTC) + timedelta(days=10, hours=10)).isoformat()
    valid_end = (datetime.now(UTC) + timedelta(days=10, hours=12)).isoformat()

    # Nonexistent provider -> 404
    res_404 = client.get(
        f"/api/v1/providers/{uuid.uuid4()}/availability",
        params={"start_time": valid_start, "end_time": valid_end},
        headers={"Authorization": cust_token},
    )
    assert res_404.status_code == status.HTTP_404_NOT_FOUND

    # Non-provider user (customer) -> 400
    res_400 = client.get(
        f"/api/v1/providers/{customer.id}/availability",
        params={"start_time": valid_start, "end_time": valid_end},
        headers={"Authorization": cust_token},
    )
    assert res_400.status_code == status.HTTP_400_BAD_REQUEST

    # Naive start datetime -> 422
    res_naive = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": "2026-10-15T10:00:00", "end_time": valid_end},
        headers={"Authorization": cust_token},
    )
    assert res_naive.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "timezone-aware" in res_naive.text

    # Naive end datetime -> 422
    res_naive_end = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": valid_start, "end_time": "2026-10-15T12:00:00"},
        headers={"Authorization": cust_token},
    )
    assert res_naive_end.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "timezone-aware" in res_naive_end.text

    # end_time <= start_time -> 422
    res_inverted = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": valid_end, "end_time": valid_start},
        headers={"Authorization": cust_token},
    )
    assert res_inverted.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "end_time must be after start_time" in res_inverted.text

    # end_time == start_time -> 422
    res_equal = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": valid_start, "end_time": valid_start},
        headers={"Authorization": cust_token},
    )
    assert res_equal.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "end_time must be after start_time" in res_equal.text


# ===========================================================================
# 5. Booking Integration Tests
# ===========================================================================


def test_booking_integration_availability_and_conflict_consistency(
    client: TestClient, db: Session
) -> None:
    """Verify availability reflects booking creation, conflict, and cancellation."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=12, hours=14)
    end = start + timedelta(hours=2)

    # 1. Slot starts as available
    res_avail1 = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers={"Authorization": cust_token},
    )
    assert res_avail1.status_code == status.HTTP_200_OK
    assert res_avail1.json()["available"] is True

    # 2. Customer creates booking for the slot
    create_payload = {
        "provider_id": str(provider.id),
        "service_name": "TestProvider Cleaning",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }
    res_book = client.post(
        "/api/v1/bookings",
        json=create_payload,
        headers={"Authorization": cust_token},
    )
    assert res_book.status_code == status.HTTP_201_CREATED
    booking_id = res_book.json()["id"]

    # 3. Slot is now unavailable
    res_avail2 = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers={"Authorization": cust_token},
    )
    assert res_avail2.status_code == status.HTTP_200_OK
    assert res_avail2.json()["available"] is False

    # 4. Attempting another booking in the same slot directly fails with 409 Conflict
    res_book_conflict = client.post(
        "/api/v1/bookings",
        json=create_payload,
        headers={"Authorization": cust_token},
    )
    assert res_book_conflict.status_code == status.HTTP_409_CONFLICT

    # 5. Cancelling the booking frees the slot
    res_cancel = client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers={"Authorization": cust_token},
    )
    assert res_cancel.status_code == status.HTTP_200_OK

    # 6. Slot is available again
    res_avail3 = client.get(
        f"/api/v1/providers/{provider.id}/availability",
        params={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers={"Authorization": cust_token},
    )
    assert res_avail3.status_code == status.HTTP_200_OK
    assert res_avail3.json()["available"] is True

    # 7. Slot can now be booked successfully
    res_rebook = client.post(
        "/api/v1/bookings",
        json=create_payload,
        headers={"Authorization": cust_token},
    )
    assert res_rebook.status_code == status.HTTP_201_CREATED
