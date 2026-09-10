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
from app.models.enums import UserRole
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
def cleanup_booking_test_data():
    """Clean up bookings and users created for booking tests after each test."""
    yield
    session = SessionLocal()
    try:
        # Delete test bookings first
        bookings = (
            session.execute(
                select(Booking).where(Booking.service_name.like("TestBooking%"))
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
                select(User).where(User.email.like("%@bookingtest.example.com"))
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
        email=f"{role.value}_{uuid.uuid4().hex[:8]}@bookingtest.example.com",
        password_hash=hash_password("Password123!"),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(subject=str(user.id))
    return user, f"Bearer {token}"


# ===========================================================================
# 1. Authentication Tests
# ===========================================================================


def test_unauthenticated_requests_rejected(client: TestClient) -> None:
    """Verify all booking endpoints reject unauthenticated requests with 401."""
    fake_id = str(uuid.uuid4())

    res_post = client.post("/api/v1/bookings", json={})
    assert res_post.status_code == status.HTTP_401_UNAUTHORIZED
    res_get = client.get("/api/v1/bookings")
    assert res_get.status_code == status.HTTP_401_UNAUTHORIZED
    assert (
        client.get(f"/api/v1/bookings/{fake_id}").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.patch(f"/api/v1/bookings/{fake_id}", json={}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.post(f"/api/v1/bookings/{fake_id}/cancel").status_code
        == status.HTTP_401_UNAUTHORIZED
    )


# ===========================================================================
# 2. Booking Creation Tests
# ===========================================================================


def test_create_booking_success(client: TestClient, db: Session) -> None:
    """Verify customer can successfully create a booking with valid payload."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=2, hours=10)
    end = start + timedelta(hours=2)

    payload = {
        "provider_id": str(provider.id),
        "service_name": "TestBooking House Cleaning",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }

    response = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert "id" in data
    assert data["customer_id"] == str(customer.id)
    assert data["provider_id"] == str(provider.id)
    assert data["service_name"] == "TestBooking House Cleaning"
    assert data["status"] == "pending"


def test_create_booking_customer_id_cannot_be_spoofed(
    client: TestClient, db: Session
) -> None:
    """Verify client cannot spoof customer_id by passing it in request JSON."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    victim, _ = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=3, hours=10)
    end = start + timedelta(hours=1)

    payload = {
        "customer_id": str(victim.id),  # Attempted spoof
        "provider_id": str(provider.id),
        "service_name": "TestBooking Spoof Attempt",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }

    response = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    # Must belong to caller, NOT the victim
    assert data["customer_id"] == str(customer.id)
    assert data["customer_id"] != str(victim.id)


def test_create_booking_provider_cannot_book_themselves(
    client: TestClient, db: Session
) -> None:
    """Verify provider cannot book themselves as customer and provider."""
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=2)
    end = start + timedelta(hours=2)

    payload = {
        "provider_id": str(provider.id),
        "service_name": "TestBooking Self Booking",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }

    response = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={"Authorization": prov_token},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "cannot book themselves" in response.json()["detail"]


def test_create_booking_nonexistent_provider(client: TestClient, db: Session) -> None:
    """Verify booking with a non-existent provider returns 404."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    random_id = str(uuid.uuid4())

    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=1)

    payload = {
        "provider_id": random_id,
        "service_name": "TestBooking Plumbing",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }

    response = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Provider not found" in response.json()["detail"]


def test_create_booking_selected_user_is_not_provider(
    client: TestClient, db: Session
) -> None:
    """Verify selecting a customer as provider returns 400 Bad Request."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    other_cust, _ = create_user_with_token(db, UserRole.CUSTOMER)

    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=1)

    payload = {
        "provider_id": str(other_cust.id),  # Customer, not a Provider!
        "service_name": "TestBooking Painting",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }

    response = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "not registered as a service provider" in response.json()["detail"]


def test_create_booking_invalid_time_range(client: TestClient, db: Session) -> None:
    """Verify end_time <= start_time returns 422 Unprocessable Entity."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=1)
    end = start - timedelta(hours=1)  # Invalid

    payload = {
        "provider_id": str(provider.id),
        "service_name": "TestBooking Time Check",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }

    response = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_booking_naive_datetime_rejected(
    client: TestClient, db: Session
) -> None:
    """Verify naive datetimes without timezone raise 422 validation error."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    payload = {
        "provider_id": str(provider.id),
        "service_name": "TestBooking Naive Time",
        "start_time": "2026-10-15T10:00:00",  # No tz offset
        "end_time": "2026-10-15T12:00:00",
    }

    response = client.post(
        "/api/v1/bookings",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "timezone-aware" in response.text


# ===========================================================================
# 3. Conflict Detection Tests
# ===========================================================================


def test_create_booking_overlapping_conflict_rejected(
    client: TestClient, db: Session
) -> None:
    """Verify overlapping booking for the same provider returns 409 Conflict."""
    _, cust_token1 = create_user_with_token(db, UserRole.CUSTOMER)
    _, cust_token2 = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start1 = datetime.now(UTC) + timedelta(days=4, hours=10)
    end1 = start1 + timedelta(hours=2)

    # First booking: 10:00 - 12:00
    res1 = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(provider.id),
            "service_name": "TestBooking First",
            "start_time": start1.isoformat(),
            "end_time": end1.isoformat(),
        },
        headers={"Authorization": cust_token1},
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # Overlapping second booking: 11:00 - 13:00
    start2 = start1 + timedelta(hours=1)
    end2 = start2 + timedelta(hours=2)

    res2 = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(provider.id),
            "service_name": "TestBooking Overlap",
            "start_time": start2.isoformat(),
            "end_time": end2.isoformat(),
        },
        headers={"Authorization": cust_token2},
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "overlapping booking" in res2.json()["detail"]


def test_create_booking_adjacent_times_allowed(client: TestClient, db: Session) -> None:
    """Verify adjacent back-to-back bookings for same provider are allowed."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    base_time = datetime.now(UTC) + timedelta(days=5, hours=10)
    mid_time = base_time + timedelta(hours=2)
    end_time = mid_time + timedelta(hours=2)

    # Booking 1: 10:00 - 12:00
    res1 = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(provider.id),
            "service_name": "TestBooking Slot 1",
            "start_time": base_time.isoformat(),
            "end_time": mid_time.isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # Booking 2 starts exactly when Booking 1 ends: 12:00 - 14:00
    res2 = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(provider.id),
            "service_name": "TestBooking Slot 2",
            "start_time": mid_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res2.status_code == status.HTTP_201_CREATED


def test_create_booking_cancelled_booking_does_not_conflict(
    client: TestClient, db: Session
) -> None:
    """Verify cancelled bookings do not block new bookings for the same time slot."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=6, hours=10)
    end = start + timedelta(hours=2)

    # Create initial booking
    res1 = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(provider.id),
            "service_name": "TestBooking To Cancel",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    booking_id = res1.json()["id"]

    # Cancel it
    res_cancel = client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers={"Authorization": cust_token},
    )
    assert res_cancel.status_code == status.HTTP_200_OK

    # Create new booking overlapping the same slot -> Must succeed
    res2 = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(provider.id),
            "service_name": "TestBooking New Slot",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers={"Authorization": cust_token},
    )
    assert res2.status_code == status.HTTP_201_CREATED


# ===========================================================================
# 4. Visibility & Filtering Tests (List)
# ===========================================================================


def test_list_bookings_role_based_visibility(client: TestClient, db: Session) -> None:
    """Verify customer, provider, and admin visibility rules when listing bookings."""
    c1, c1_token = create_user_with_token(db, UserRole.CUSTOMER, "Customer One")
    c2, c2_token = create_user_with_token(db, UserRole.CUSTOMER, "Customer Two")
    p1, p1_token = create_user_with_token(db, UserRole.PROVIDER, "Provider One")
    p2, _ = create_user_with_token(db, UserRole.PROVIDER, "Provider Two")
    _, admin_token = create_user_with_token(db, UserRole.ADMIN, "Admin")

    # Booking 1: C1 + P1
    t1 = datetime.now(UTC) + timedelta(days=7, hours=10)
    client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p1.id),
            "service_name": "TestBooking C1-P1",
            "start_time": t1.isoformat(),
            "end_time": (t1 + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c1_token},
    )

    # Booking 2: C2 + P2
    t2 = datetime.now(UTC) + timedelta(days=7, hours=12)
    client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p2.id),
            "service_name": "TestBooking C2-P2",
            "start_time": t2.isoformat(),
            "end_time": (t2 + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c2_token},
    )

    # Customer 1 sees only Booking 1
    c1_list = client.get("/api/v1/bookings", headers={"Authorization": c1_token}).json()
    assert len(c1_list) == 1
    assert c1_list[0]["customer_id"] == str(c1.id)

    # Customer 2 sees only Booking 2
    c2_list = client.get("/api/v1/bookings", headers={"Authorization": c2_token}).json()
    assert len(c2_list) == 1
    assert c2_list[0]["customer_id"] == str(c2.id)

    # Provider 1 sees only Booking 1
    p1_list = client.get("/api/v1/bookings", headers={"Authorization": p1_token}).json()
    assert len(p1_list) == 1
    assert p1_list[0]["provider_id"] == str(p1.id)

    # Admin sees both bookings
    admin_list = client.get(
        "/api/v1/bookings", headers={"Authorization": admin_token}
    ).json()
    assert len(admin_list) >= 2


def test_list_bookings_status_filter_and_pagination(
    client: TestClient, db: Session
) -> None:
    """Verify status query filter and skip/limit pagination parameters."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, _ = create_user_with_token(db, UserRole.PROVIDER)

    base = datetime.now(UTC) + timedelta(days=8)
    created_ids: list[str] = []
    for i in range(3):
        t = base + timedelta(hours=i * 2)
        res = client.post(
            "/api/v1/bookings",
            json={
                "provider_id": str(p.id),
                "service_name": f"TestBooking Page {i}",
                "start_time": t.isoformat(),
                "end_time": (t + timedelta(hours=1)).isoformat(),
            },
            headers={"Authorization": c_token},
        )
        created_ids.append(res.json()["id"])

    # Cancel the second booking
    client.post(
        f"/api/v1/bookings/{created_ids[1]}/cancel",
        headers={"Authorization": c_token},
    )

    # Filter status=pending
    pending_res = client.get(
        "/api/v1/bookings?status=pending",
        headers={"Authorization": c_token},
    )
    assert len(pending_res.json()) == 2

    # Filter status=cancelled
    cancelled_res = client.get(
        "/api/v1/bookings?status=cancelled",
        headers={"Authorization": c_token},
    )
    assert len(cancelled_res.json()) == 1

    # Test pagination: limit=1
    paginated_res = client.get(
        "/api/v1/bookings?limit=1",
        headers={"Authorization": c_token},
    )
    assert len(paginated_res.json()) == 1


# ===========================================================================
# 5. Single Booking Retrieval Tests
# ===========================================================================


def test_get_booking_authorization(client: TestClient, db: Session) -> None:
    """Verify single booking retrieval respects role-based authorization."""
    c1, c1_token = create_user_with_token(db, UserRole.CUSTOMER)
    _, c2_token = create_user_with_token(db, UserRole.CUSTOMER)
    p1, p1_token = create_user_with_token(db, UserRole.PROVIDER)
    _, p2_token = create_user_with_token(db, UserRole.PROVIDER)
    _, admin_token = create_user_with_token(db, UserRole.ADMIN)

    t = datetime.now(UTC) + timedelta(days=9)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p1.id),
            "service_name": "TestBooking Auth Check",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c1_token},
    )
    booking_id = create_res.json()["id"]

    # Owner customer: allowed
    res_c1 = client.get(
        f"/api/v1/bookings/{booking_id}", headers={"Authorization": c1_token}
    )
    assert res_c1.status_code == status.HTTP_200_OK

    # Assigned provider: allowed
    res_p1 = client.get(
        f"/api/v1/bookings/{booking_id}", headers={"Authorization": p1_token}
    )
    assert res_p1.status_code == status.HTTP_200_OK

    # Admin: allowed
    res_admin = client.get(
        f"/api/v1/bookings/{booking_id}", headers={"Authorization": admin_token}
    )
    assert res_admin.status_code == status.HTTP_200_OK

    # Unrelated customer: 403 Forbidden
    res_c2 = client.get(
        f"/api/v1/bookings/{booking_id}", headers={"Authorization": c2_token}
    )
    assert res_c2.status_code == status.HTTP_403_FORBIDDEN

    # Unrelated provider: 403 Forbidden
    res_p2 = client.get(
        f"/api/v1/bookings/{booking_id}", headers={"Authorization": p2_token}
    )
    assert res_p2.status_code == status.HTTP_403_FORBIDDEN


def test_get_booking_not_found_and_malformed_uuid(
    client: TestClient, db: Session
) -> None:
    """Verify non-existent UUID returns 404 and malformed UUID returns 422."""
    _, admin_token = create_user_with_token(db, UserRole.ADMIN)

    random_id = str(uuid.uuid4())
    res_404 = client.get(
        f"/api/v1/bookings/{random_id}",
        headers={"Authorization": admin_token},
    )
    assert res_404.status_code == status.HTTP_404_NOT_FOUND

    res_422 = client.get(
        "/api/v1/bookings/not-a-uuid",
        headers={"Authorization": admin_token},
    )
    assert res_422.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ===========================================================================
# 6. Update (PATCH) & Status Transition Tests
# ===========================================================================


def test_patch_booking_service_name_and_reschedule(
    client: TestClient, db: Session
) -> None:
    """Verify customer can update service name and reschedule booking."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, _ = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=10, hours=10)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "TestBooking Original",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # Reschedule to 14:00 - 16:00
    new_start = datetime.now(UTC) + timedelta(days=10, hours=14)
    new_end = new_start + timedelta(hours=2)

    patch_res = client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={
            "service_name": "TestBooking Rescheduled",
            "start_time": new_start.isoformat(),
            "end_time": new_end.isoformat(),
        },
        headers={"Authorization": c_token},
    )
    assert patch_res.status_code == status.HTTP_200_OK
    data = patch_res.json()
    assert data["service_name"] == "TestBooking Rescheduled"


def test_patch_booking_ownership_fields_immutable(
    client: TestClient, db: Session
) -> None:
    """Verify customer_id and provider_id cannot be changed via PATCH."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, _ = create_user_with_token(db, UserRole.PROVIDER)
    other_user, _ = create_user_with_token(db, UserRole.CUSTOMER)

    t = datetime.now(UTC) + timedelta(days=11)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "TestBooking Immutability",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # Attempt to change customer_id and provider_id
    patch_res = client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={
            "customer_id": str(other_user.id),
            "provider_id": str(other_user.id),
            "service_name": "TestBooking Mutate Attempt",
        },
        headers={"Authorization": c_token},
    )
    assert patch_res.status_code == status.HTTP_200_OK
    data = patch_res.json()
    assert data["customer_id"] == str(c.id)  # Unchanged
    assert data["provider_id"] == str(p.id)  # Unchanged


def test_patch_booking_status_transitions_by_roles(
    client: TestClient, db: Session
) -> None:
    """Verify role-based status transition rules: PENDING -> CONFIRMED -> COMPLETED."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, p_token = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=12)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "TestBooking Transition",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # 1. Customer cannot confirm booking (403 Forbidden)
    res_cust_confirm = client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "confirmed"},
        headers={"Authorization": c_token},
    )
    assert res_cust_confirm.status_code == status.HTTP_403_FORBIDDEN

    # 2. Provider can confirm booking (200 OK)
    res_prov_confirm = client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "confirmed"},
        headers={"Authorization": p_token},
    )
    assert res_prov_confirm.status_code == status.HTTP_200_OK
    assert res_prov_confirm.json()["status"] == "confirmed"

    # 3. Provider can complete confirmed booking (200 OK)
    res_prov_complete = client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "completed"},
        headers={"Authorization": p_token},
    )
    assert res_prov_complete.status_code == status.HTTP_200_OK
    assert res_prov_complete.json()["status"] == "completed"

    # 4. Completed booking is terminal: cannot be revived or modified (400 Bad Request)
    res_revive = client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "pending"},
        headers={"Authorization": p_token},
    )
    assert res_revive.status_code == status.HTTP_400_BAD_REQUEST


def test_patch_booking_invalid_status_transition_rejected(
    client: TestClient, db: Session
) -> None:
    """Verify illegal transitions (e.g. PENDING -> COMPLETED directly) are rejected."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, p_token = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=13)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "TestBooking Illegal Skip",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # Direct PENDING -> COMPLETED is illegal
    res = client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "completed"},
        headers={"Authorization": p_token},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot transition booking status" in res.json()["detail"]


# ===========================================================================
# 7. Cancellation Endpoint Tests
# ===========================================================================


def test_cancel_booking_success_and_idempotency(
    client: TestClient, db: Session
) -> None:
    """Verify cancellation endpoint behavior, permissions, and repeat cancellation."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, _ = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=14)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "TestBooking Cancel Path",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # First cancel succeeds
    cancel_res1 = client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers={"Authorization": c_token},
    )
    assert cancel_res1.status_code == status.HTTP_200_OK
    assert cancel_res1.json()["status"] == "cancelled"

    # Second cancel fails with 400 Bad Request
    cancel_res2 = client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers={"Authorization": c_token},
    )
    assert cancel_res2.status_code == status.HTTP_400_BAD_REQUEST
    assert "already cancelled" in cancel_res2.json()["detail"]


def test_cancel_booking_completed_fails(client: TestClient, db: Session) -> None:
    """Verify attempting to cancel a completed booking returns 400 Bad Request."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, p_token = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=15)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "TestBooking Completed Cancel",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # Provider confirms and completes
    client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "confirmed"},
        headers={"Authorization": p_token},
    )
    client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "completed"},
        headers={"Authorization": p_token},
    )

    # Cancel must fail
    res = client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers={"Authorization": c_token},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot cancel an already completed booking" in res.json()["detail"]


def test_cancel_booking_unauthorized_user_forbidden(
    client: TestClient, db: Session
) -> None:
    """Verify unrelated user cannot cancel someone else's booking."""
    c1, c1_token = create_user_with_token(db, UserRole.CUSTOMER)
    _, c2_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, _ = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=16)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "TestBooking Unauth Cancel",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c1_token},
    )
    booking_id = create_res.json()["id"]

    # Unrelated customer attempts cancel
    res = client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers={"Authorization": c2_token},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# Booking DELETE (Business-Safe Cancellation) Tests
# ===========================================================================


def test_delete_booking_pending_customer_success(
    client: TestClient, db: Session
) -> None:
    """Verify customer can delete own PENDING booking (transitions to CANCELLED)."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, _ = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=20)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "Safe Delete Test",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    booking_id = create_res.json()["id"]

    # DELETE returns 204 No Content
    del_res = client.delete(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": c_token},
    )
    assert del_res.status_code == status.HTTP_204_NO_CONTENT

    # Verify status is now CANCELLED and booking record is preserved
    get_res = client.get(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": c_token},
    )
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["status"] == "cancelled"


def test_delete_booking_confirmed_rejected(client: TestClient, db: Session) -> None:
    """Verify confirmed bookings cannot be deleted directly via DELETE verb."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, p_token = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=21)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "Confirmed Delete Test",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # Provider confirms booking
    client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "confirmed"},
        headers={"Authorization": p_token},
    )

    # Customer tries DELETE on confirmed booking
    del_res = client.delete(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": c_token},
    )
    assert del_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Confirmed bookings cannot be deleted directly" in del_res.json()["detail"]


def test_delete_booking_completed_rejected(client: TestClient, db: Session) -> None:
    """Verify completed bookings cannot be deleted to protect historical records."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, p_token = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=22)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "Completed Delete Test",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # Confirm and complete
    client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "confirmed"},
        headers={"Authorization": p_token},
    )
    client.patch(
        f"/api/v1/bookings/{booking_id}",
        json={"status": "completed"},
        headers={"Authorization": p_token},
    )

    # Attempt DELETE
    del_res = client.delete(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": c_token},
    )
    assert del_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "historical business records" in del_res.json()["detail"]


def test_delete_booking_already_cancelled_rejected(
    client: TestClient, db: Session
) -> None:
    """Verify deleting an already cancelled booking returns 400 Bad Request."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, _ = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=23)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "Already Cancelled Delete Test",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # Delete once -> 204
    res1 = client.delete(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": c_token},
    )
    assert res1.status_code == status.HTTP_204_NO_CONTENT

    # Delete again -> 400
    res2 = client.delete(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": c_token},
    )
    assert res2.status_code == status.HTTP_400_BAD_REQUEST
    assert "already cancelled" in res2.json()["detail"]


def test_delete_booking_unauthorized_user_and_provider_forbidden(
    client: TestClient, db: Session
) -> None:
    """Verify unrelated customer and provider are forbidden from deleting booking."""
    c1, c1_token = create_user_with_token(db, UserRole.CUSTOMER)
    _, c2_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, p_token = create_user_with_token(db, UserRole.PROVIDER)

    t = datetime.now(UTC) + timedelta(days=24)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "Unauth Delete Test",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c1_token},
    )
    booking_id = create_res.json()["id"]

    # Unrelated customer -> 403
    res_c2 = client.delete(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": c2_token},
    )
    assert res_c2.status_code == status.HTTP_403_FORBIDDEN

    # Provider -> 403
    res_p = client.delete(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": p_token},
    )
    assert res_p.status_code == status.HTTP_403_FORBIDDEN


def test_delete_booking_admin_success(client: TestClient, db: Session) -> None:
    """Verify admin can delete a PENDING booking."""
    c, c_token = create_user_with_token(db, UserRole.CUSTOMER)
    p, _ = create_user_with_token(db, UserRole.PROVIDER)
    _, admin_token = create_user_with_token(db, UserRole.ADMIN)

    t = datetime.now(UTC) + timedelta(days=25)
    create_res = client.post(
        "/api/v1/bookings",
        json={
            "provider_id": str(p.id),
            "service_name": "Admin Delete Test",
            "start_time": t.isoformat(),
            "end_time": (t + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": c_token},
    )
    booking_id = create_res.json()["id"]

    # Admin deletes -> 204
    del_res = client.delete(
        f"/api/v1/bookings/{booking_id}",
        headers={"Authorization": admin_token},
    )
    assert del_res.status_code == status.HTTP_204_NO_CONTENT
