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
from app.models.review import Review
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
def cleanup_review_test_data():
    """Clean up test reviews, bookings, and users after each test."""
    yield
    session = SessionLocal()
    try:
        # Delete test reviews first
        reviews = (
            session.execute(
                select(Review).where(
                    Review.comment.like("TestReview%")
                    | Review.comment.like("Updated TestReview%")
                )
            )
            .scalars()
            .all()
        )
        for r in reviews:
            session.delete(r)
        session.commit()

        # Delete test bookings
        bookings = (
            session.execute(
                select(Booking).where(Booking.service_name.like("TestReview%"))
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
                select(User).where(User.email.like("%@reviewtest.example.com"))
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
        email=f"{role.value}_{uuid.uuid4().hex[:8]}@reviewtest.example.com",
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
    booking_status: BookingStatus = BookingStatus.COMPLETED,
    service_name: str = "TestReview Service",
) -> Booking:
    """Helper creating a booking reservation in the requested state."""
    start = datetime.now(UTC) - timedelta(days=1, hours=2)
    end = start + timedelta(hours=2)
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name=service_name,
        start_time=start,
        end_time=end,
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
    """Verify all review endpoints reject unauthenticated requests with 401."""
    fake_id = str(uuid.uuid4())

    assert (
        client.post("/api/v1/reviews", json={}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert client.get("/api/v1/reviews").status_code == status.HTTP_401_UNAUTHORIZED
    assert (
        client.get(f"/api/v1/reviews/{fake_id}").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.patch(f"/api/v1/reviews/{fake_id}", json={}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.delete(f"/api/v1/reviews/{fake_id}").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.get(f"/api/v1/providers/{fake_id}/reviews/summary").status_code
        == status.HTTP_401_UNAUTHORIZED
    )


# ===========================================================================
# 2. Review Creation Tests
# ===========================================================================


def test_create_review_success(client: TestClient, db: Session) -> None:
    """Verify customer can successfully create a review for their completed booking."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    payload = {
        "booking_id": str(booking.id),
        "rating": 5,
        "comment": "TestReview Excellent work done on time!",
    }

    response = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "id" in data
    assert data["booking_id"] == str(booking.id)
    assert data["customer_id"] == str(customer.id)
    assert data["provider_id"] == str(provider.id)
    assert data["rating"] == 5
    assert data["comment"] == "TestReview Excellent work done on time!"
    assert "created_at" in data
    assert "updated_at" in data


def test_create_review_only_customer_allowed(client: TestClient, db: Session) -> None:
    """Verify non-customer roles (provider, admin) receive 403 when creating reviews."""
    customer, _ = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)
    admin, admin_token = create_user_with_token(db, UserRole.ADMIN)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    payload = {
        "booking_id": str(booking.id),
        "rating": 4,
        "comment": "TestReview Provider attempting review",
    }

    # Provider attempt
    res_prov = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": prov_token},
    )
    assert res_prov.status_code == status.HTTP_403_FORBIDDEN

    # Admin attempt
    res_admin = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": admin_token},
    )
    assert res_admin.status_code == status.HTTP_403_FORBIDDEN


def test_create_review_unauthorized_for_other_customer_booking(
    client: TestClient, db: Session
) -> None:
    """Verify customer cannot review another customer's completed booking."""
    cust_a, _ = create_user_with_token(db, UserRole.CUSTOMER)
    cust_b, token_b = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking_a = create_test_booking(db, cust_a, provider, BookingStatus.COMPLETED)

    payload = {
        "booking_id": str(booking_a.id),
        "rating": 5,
        "comment": "TestReview Customer B spoofing customer A",
    }

    response = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": token_b},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Not authorized" in response.json()["detail"]


def test_create_review_nonexistent_booking(client: TestClient, db: Session) -> None:
    """Verify 404 is returned when attempting to review a nonexistent booking."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    fake_booking_id = str(uuid.uuid4())

    payload = {
        "booking_id": fake_booking_id,
        "rating": 4,
        "comment": "TestReview Nonexistent booking",
    }

    response = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Booking not found" in response.json()["detail"]


@pytest.mark.parametrize(
    "invalid_status",
    [BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.CANCELLED],
)
def test_create_review_non_completed_bookings_rejected(
    client: TestClient, db: Session, invalid_status: BookingStatus
) -> None:
    """Verify reviews cannot be submitted for bookings that are not COMPLETED."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, invalid_status)

    payload = {
        "booking_id": str(booking.id),
        "rating": 4,
        "comment": f"TestReview Booking in {invalid_status.value} status",
    }

    response = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Only completed bookings can be reviewed" in response.json()["detail"]


def test_create_review_duplicate_booking_rejected(
    client: TestClient, db: Session
) -> None:
    """Verify duplicate review for the same booking returns a clean 409 Conflict."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    payload = {
        "booking_id": str(booking.id),
        "rating": 5,
        "comment": "TestReview Initial review",
    }

    # First review succeeds
    res1 = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # Second review fails with 409 Conflict
    res2 = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in res2.json()["detail"]


def test_create_review_rating_validation(client: TestClient, db: Session) -> None:
    """Verify rating bounds (1 to 5) are strictly validated."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking1 = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    # Rating 0 rejected
    res_0 = client.post(
        "/api/v1/reviews",
        json={"booking_id": str(booking1.id), "rating": 0},
        headers={"Authorization": cust_token},
    )
    assert res_0.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Rating 6 rejected
    res_6 = client.post(
        "/api/v1/reviews",
        json={"booking_id": str(booking1.id), "rating": 6},
        headers={"Authorization": cust_token},
    )
    assert res_6.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Rating 1 succeeds
    res_1 = client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(booking1.id),
            "rating": 1,
            "comment": "TestReview Lowest",
        },
        headers={"Authorization": cust_token},
    )
    assert res_1.status_code == status.HTTP_201_CREATED
    assert res_1.json()["rating"] == 1


def test_create_review_ignores_spoofed_identities(
    client: TestClient, db: Session
) -> None:
    """Verify customer_id and provider_id cannot be spoofed in request payload."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    spoofed_customer_id = str(uuid.uuid4())
    spoofed_provider_id = str(uuid.uuid4())

    payload = {
        "booking_id": str(booking.id),
        "customer_id": spoofed_customer_id,
        "provider_id": spoofed_provider_id,
        "rating": 5,
        "comment": "TestReview Trying to spoof customer and provider",
    }

    response = client.post(
        "/api/v1/reviews",
        json=payload,
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["customer_id"] == str(customer.id)
    assert data["provider_id"] == str(provider.id)
    assert data["customer_id"] != spoofed_customer_id
    assert data["provider_id"] != spoofed_provider_id


def test_create_review_comment_length_validation(
    client: TestClient, db: Session
) -> None:
    """Verify comment length validation (max 2000 characters)."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    # Max length 2000 is accepted
    long_comment = "TestReview " + "A" * 1980
    res_valid = client.post(
        "/api/v1/reviews",
        json={"booking_id": str(booking.id), "rating": 5, "comment": long_comment},
        headers={"Authorization": cust_token},
    )
    assert res_valid.status_code == status.HTTP_201_CREATED

    booking2 = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)
    # Length > 2000 is rejected
    too_long_comment = "TestReview " + "A" * 2000
    res_invalid = client.post(
        "/api/v1/reviews",
        json={"booking_id": str(booking2.id), "rating": 5, "comment": too_long_comment},
        headers={"Authorization": cust_token},
    )
    assert res_invalid.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ===========================================================================
# 3. Review Retrieval Tests
# ===========================================================================


def test_get_review_by_id_authorized_users(client: TestClient, db: Session) -> None:
    """Verify author customer, assigned provider, and admin can retrieve review."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)
    admin, admin_token = create_user_with_token(db, UserRole.ADMIN)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
            "comment": "TestReview Retrieval",
        },
        headers={"Authorization": cust_token},
    )
    review_id = create_res.json()["id"]

    # Customer can retrieve
    res_cust = client.get(
        f"/api/v1/reviews/{review_id}", headers={"Authorization": cust_token}
    )
    assert res_cust.status_code == status.HTTP_200_OK
    assert res_cust.json()["id"] == review_id

    # Provider can retrieve
    res_prov = client.get(
        f"/api/v1/reviews/{review_id}", headers={"Authorization": prov_token}
    )
    assert res_prov.status_code == status.HTTP_200_OK
    assert res_prov.json()["id"] == review_id

    # Admin can retrieve
    res_admin = client.get(
        f"/api/v1/reviews/{review_id}", headers={"Authorization": admin_token}
    )
    assert res_admin.status_code == status.HTTP_200_OK
    assert res_admin.json()["id"] == review_id


def test_get_review_by_id_forbidden_for_unrelated_users(
    client: TestClient, db: Session
) -> None:
    """Verify unrelated customers and providers cannot retrieve a review."""
    cust_a, cust_a_token = create_user_with_token(db, UserRole.CUSTOMER)
    prov_a, _ = create_user_with_token(db, UserRole.PROVIDER)
    cust_b, cust_b_token = create_user_with_token(db, UserRole.CUSTOMER)
    prov_b, prov_b_token = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, cust_a, prov_a, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 5,
            "comment": "TestReview Forbidden get",
        },
        headers={"Authorization": cust_a_token},
    )
    review_id = create_res.json()["id"]

    # Unrelated customer attempt -> 403
    res_cust_b = client.get(
        f"/api/v1/reviews/{review_id}", headers={"Authorization": cust_b_token}
    )
    assert res_cust_b.status_code == status.HTTP_403_FORBIDDEN

    # Unrelated provider attempt -> 403
    res_prov_b = client.get(
        f"/api/v1/reviews/{review_id}", headers={"Authorization": prov_b_token}
    )
    assert res_prov_b.status_code == status.HTTP_403_FORBIDDEN


def test_get_review_by_id_not_found_and_invalid_uuid(
    client: TestClient, db: Session
) -> None:
    """Verify 404 for nonexistent UUID and 422 for malformed UUID format."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)

    fake_id = str(uuid.uuid4())
    res_not_found = client.get(
        f"/api/v1/reviews/{fake_id}", headers={"Authorization": cust_token}
    )
    assert res_not_found.status_code == status.HTTP_404_NOT_FOUND

    res_malformed = client.get(
        "/api/v1/reviews/not-a-valid-uuid", headers={"Authorization": cust_token}
    )
    assert res_malformed.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ===========================================================================
# 4. Review Listing Tests
# ===========================================================================


def test_list_reviews_role_visibility(client: TestClient, db: Session) -> None:
    """Verify review listing filters by caller role (customer, provider, admin)."""
    cust1, token1 = create_user_with_token(db, UserRole.CUSTOMER)
    cust2, token2 = create_user_with_token(db, UserRole.CUSTOMER)
    prov1, prov_token1 = create_user_with_token(db, UserRole.PROVIDER)
    prov2, _ = create_user_with_token(db, UserRole.PROVIDER)
    admin, admin_token = create_user_with_token(db, UserRole.ADMIN)

    # Booking 1: cust1 with prov1
    b1 = create_test_booking(db, cust1, prov1, BookingStatus.COMPLETED)
    # Booking 2: cust2 with prov1
    b2 = create_test_booking(db, cust2, prov1, BookingStatus.COMPLETED)
    # Booking 3: cust1 with prov2
    b3 = create_test_booking(db, cust1, prov2, BookingStatus.COMPLETED)

    client.post(
        "/api/v1/reviews",
        json={"booking_id": str(b1.id), "rating": 5, "comment": "TestReview 1"},
        headers={"Authorization": token1},
    )
    client.post(
        "/api/v1/reviews",
        json={"booking_id": str(b2.id), "rating": 4, "comment": "TestReview 2"},
        headers={"Authorization": token2},
    )
    client.post(
        "/api/v1/reviews",
        json={"booking_id": str(b3.id), "rating": 3, "comment": "TestReview 3"},
        headers={"Authorization": token1},
    )

    # Customer 1 sees reviews for b1 and b3 (total 2)
    res_c1 = client.get("/api/v1/reviews", headers={"Authorization": token1})
    assert res_c1.status_code == status.HTTP_200_OK
    assert len(res_c1.json()) == 2
    assert all(r["customer_id"] == str(cust1.id) for r in res_c1.json())

    # Provider 1 sees reviews for b1 and b2 (total 2)
    res_p1 = client.get("/api/v1/reviews", headers={"Authorization": prov_token1})
    assert res_p1.status_code == status.HTTP_200_OK
    assert len(res_p1.json()) == 2
    assert all(r["provider_id"] == str(prov1.id) for r in res_p1.json())

    # Admin sees all reviews (at least 3)
    res_admin = client.get("/api/v1/reviews", headers={"Authorization": admin_token})
    assert res_admin.status_code == status.HTTP_200_OK
    admin_reviews = [
        r for r in res_admin.json() if "TestReview" in (r["comment"] or "")
    ]
    assert len(admin_reviews) == 3


def test_list_reviews_filtering_and_pagination(client: TestClient, db: Session) -> None:
    """Verify review listing filtering by provider_id, rating, and pagination."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    admin, admin_token = create_user_with_token(db, UserRole.ADMIN)

    # Create 3 completed bookings
    b1 = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)
    b2 = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)
    b3 = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    client.post(
        "/api/v1/reviews",
        json={"booking_id": str(b1.id), "rating": 5, "comment": "TestReview Rating 5"},
        headers={"Authorization": cust_token},
    )
    client.post(
        "/api/v1/reviews",
        json={"booking_id": str(b2.id), "rating": 3, "comment": "TestReview Rating 3"},
        headers={"Authorization": cust_token},
    )
    client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(b3.id),
            "rating": 5,
            "comment": "TestReview Rating 5 Second",
        },
        headers={"Authorization": cust_token},
    )

    # Filter by rating 5
    res_r5 = client.get(
        "/api/v1/reviews?rating=5",
        headers={"Authorization": admin_token},
    )
    assert res_r5.status_code == status.HTTP_200_OK
    r5_reviews = [r for r in res_r5.json() if "TestReview" in (r["comment"] or "")]
    assert len(r5_reviews) == 2
    assert all(r["rating"] == 5 for r in r5_reviews)

    # Filter by provider_id
    res_prov = client.get(
        f"/api/v1/reviews?provider_id={provider.id}",
        headers={"Authorization": admin_token},
    )
    assert res_prov.status_code == status.HTTP_200_OK
    p_reviews = [r for r in res_prov.json() if "TestReview" in (r["comment"] or "")]
    assert len(p_reviews) == 3

    # Pagination: limit 1, skip 1
    res_page = client.get(
        f"/api/v1/reviews?provider_id={provider.id}&limit=1&skip=1",
        headers={"Authorization": admin_token},
    )
    assert res_page.status_code == status.HTTP_200_OK
    assert len(res_page.json()) == 1


# ===========================================================================
# 5. Review Update Tests
# ===========================================================================


def test_update_review_author_customer_success(client: TestClient, db: Session) -> None:
    """Verify author customer can update rating and comment."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 3,
            "comment": "TestReview Original",
        },
        headers={"Authorization": cust_token},
    )
    review_id = create_res.json()["id"]

    update_payload = {
        "rating": 5,
        "comment": "Updated TestReview Excellent service upon reflection!",
    }
    update_res = client.patch(
        f"/api/v1/reviews/{review_id}",
        json=update_payload,
        headers={"Authorization": cust_token},
    )
    assert update_res.status_code == status.HTTP_200_OK
    data = update_res.json()
    assert data["id"] == review_id
    assert data["rating"] == 5
    assert data["comment"] == "Updated TestReview Excellent service upon reflection!"


def test_update_review_forbidden_for_non_author(
    client: TestClient, db: Session
) -> None:
    """Verify non-author users cannot update a customer's review."""
    cust_a, cust_a_token = create_user_with_token(db, UserRole.CUSTOMER)
    cust_b, cust_b_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)
    admin, admin_token = create_user_with_token(db, UserRole.ADMIN)
    booking = create_test_booking(db, cust_a, provider, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={"booking_id": str(booking.id), "rating": 3, "comment": "TestReview Orig"},
        headers={"Authorization": cust_a_token},
    )
    review_id = create_res.json()["id"]

    update_payload = {"rating": 5}

    # Provider attempt -> 403
    res_prov = client.patch(
        f"/api/v1/reviews/{review_id}",
        json=update_payload,
        headers={"Authorization": prov_token},
    )
    assert res_prov.status_code == status.HTTP_403_FORBIDDEN

    # Admin attempt -> 403 (Only the original customer can update)
    res_admin = client.patch(
        f"/api/v1/reviews/{review_id}",
        json=update_payload,
        headers={"Authorization": admin_token},
    )
    assert res_admin.status_code == status.HTTP_403_FORBIDDEN

    # Unrelated customer attempt -> 403
    res_cust_b = client.patch(
        f"/api/v1/reviews/{review_id}",
        json=update_payload,
        headers={"Authorization": cust_b_token},
    )
    assert res_cust_b.status_code == status.HTTP_403_FORBIDDEN


def test_update_review_immutable_ownership_fields(
    client: TestClient, db: Session
) -> None:
    """Verify booking_id, customer_id, provider_id cannot be modified via PATCH."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
            "comment": "TestReview Immutable",
        },
        headers={"Authorization": cust_token},
    )
    review_id = create_res.json()["id"]

    spoofed_booking = str(uuid.uuid4())
    spoofed_cust = str(uuid.uuid4())
    spoofed_prov = str(uuid.uuid4())

    update_res = client.patch(
        f"/api/v1/reviews/{review_id}",
        json={
            "booking_id": spoofed_booking,
            "customer_id": spoofed_cust,
            "provider_id": spoofed_prov,
            "rating": 5,
        },
        headers={"Authorization": cust_token},
    )
    assert update_res.status_code == status.HTTP_200_OK
    data = update_res.json()
    assert data["booking_id"] == str(booking.id)
    assert data["customer_id"] == str(customer.id)
    assert data["provider_id"] == str(provider.id)


def test_update_review_validation(client: TestClient, db: Session) -> None:
    """Verify update validation for rating bounds and nonexistent reviews."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={"booking_id": str(booking.id), "rating": 4, "comment": "TestReview Val"},
        headers={"Authorization": cust_token},
    )
    review_id = create_res.json()["id"]

    # Rating 0 rejected
    assert (
        client.patch(
            f"/api/v1/reviews/{review_id}",
            json={"rating": 0},
            headers={"Authorization": cust_token},
        ).status_code
        == status.HTTP_422_UNPROCESSABLE_ENTITY
    )

    # Rating 6 rejected
    assert (
        client.patch(
            f"/api/v1/reviews/{review_id}",
            json={"rating": 6},
            headers={"Authorization": cust_token},
        ).status_code
        == status.HTTP_422_UNPROCESSABLE_ENTITY
    )

    # Nonexistent review UUID
    assert (
        client.patch(
            f"/api/v1/reviews/{uuid.uuid4()}",
            json={"rating": 5},
            headers={"Authorization": cust_token},
        ).status_code
        == status.HTTP_404_NOT_FOUND
    )


# ===========================================================================
# 6. Review Deletion Tests
# ===========================================================================


def test_delete_review_author_customer_success(client: TestClient, db: Session) -> None:
    """Verify author customer can delete their review (returns 204 No Content)."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
            "comment": "TestReview Delete cust",
        },
        headers={"Authorization": cust_token},
    )
    review_id = create_res.json()["id"]

    # Delete review
    del_res = client.delete(
        f"/api/v1/reviews/{review_id}",
        headers={"Authorization": cust_token},
    )
    assert del_res.status_code == status.HTTP_204_NO_CONTENT

    # Verify subsequent GET returns 404
    get_res = client.get(
        f"/api/v1/reviews/{review_id}",
        headers={"Authorization": cust_token},
    )
    assert get_res.status_code == status.HTTP_404_NOT_FOUND


def test_delete_review_admin_success(client: TestClient, db: Session) -> None:
    """Verify platform admin can delete reviews (returns 204 No Content)."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    admin, admin_token = create_user_with_token(db, UserRole.ADMIN)
    booking = create_test_booking(db, customer, provider, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
            "comment": "TestReview Delete admin",
        },
        headers={"Authorization": cust_token},
    )
    review_id = create_res.json()["id"]

    del_res = client.delete(
        f"/api/v1/reviews/{review_id}",
        headers={"Authorization": admin_token},
    )
    assert del_res.status_code == status.HTTP_204_NO_CONTENT

    # Verify deleted
    get_res = client.get(
        f"/api/v1/reviews/{review_id}",
        headers={"Authorization": admin_token},
    )
    assert get_res.status_code == status.HTTP_404_NOT_FOUND


def test_delete_review_forbidden_for_provider_and_unrelated_customer(
    client: TestClient, db: Session
) -> None:
    """Verify providers and unrelated customers receive 403 when deleting reviews."""
    cust_a, cust_a_token = create_user_with_token(db, UserRole.CUSTOMER)
    cust_b, cust_b_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)
    booking = create_test_booking(db, cust_a, provider, BookingStatus.COMPLETED)

    create_res = client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
            "comment": "TestReview Forbidden del",
        },
        headers={"Authorization": cust_a_token},
    )
    review_id = create_res.json()["id"]

    # Provider attempt -> 403
    res_prov = client.delete(
        f"/api/v1/reviews/{review_id}",
        headers={"Authorization": prov_token},
    )
    assert res_prov.status_code == status.HTTP_403_FORBIDDEN

    # Unrelated customer attempt -> 403
    res_cust_b = client.delete(
        f"/api/v1/reviews/{review_id}",
        headers={"Authorization": cust_b_token},
    )
    assert res_cust_b.status_code == status.HTTP_403_FORBIDDEN


def test_delete_review_not_found(client: TestClient, db: Session) -> None:
    """Verify 404 when deleting a nonexistent review."""
    _, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    fake_id = str(uuid.uuid4())

    response = client.delete(
        f"/api/v1/reviews/{fake_id}",
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# 7. Provider Review Summary Tests
# ===========================================================================


def test_provider_review_summary_sql_aggregation(
    client: TestClient, db: Session
) -> None:
    """Verify provider summary aggregates count, avg, and distribution."""
    cust1, t1 = create_user_with_token(db, UserRole.CUSTOMER)
    cust2, t2 = create_user_with_token(db, UserRole.CUSTOMER)
    cust3, t3 = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)

    # Bookings: rating 5, rating 4, rating 5 (total 3, sum 14, avg 4.67)
    b1 = create_test_booking(db, cust1, provider, BookingStatus.COMPLETED)
    b2 = create_test_booking(db, cust2, provider, BookingStatus.COMPLETED)
    b3 = create_test_booking(db, cust3, provider, BookingStatus.COMPLETED)

    client.post(
        "/api/v1/reviews",
        json={"booking_id": str(b1.id), "rating": 5, "comment": "TestReview 5 stars"},
        headers={"Authorization": t1},
    )
    client.post(
        "/api/v1/reviews",
        json={"booking_id": str(b2.id), "rating": 4, "comment": "TestReview 4 stars"},
        headers={"Authorization": t2},
    )
    client.post(
        "/api/v1/reviews",
        json={
            "booking_id": str(b3.id),
            "rating": 5,
            "comment": "TestReview 5 stars again",
        },
        headers={"Authorization": t3},
    )

    response = client.get(
        f"/api/v1/providers/{provider.id}/reviews/summary",
        headers={"Authorization": prov_token},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["provider_id"] == str(provider.id)
    assert data["review_count"] == 3
    assert data["average_rating"] == 4.67
    assert data["rating_distribution"] == {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 1,
        "5": 2,
    }


def test_provider_review_summary_zero_reviews(client: TestClient, db: Session) -> None:
    """Verify zero reviews returns count=0, avg=0.0, and 0 for all rating keys."""
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)

    response = client.get(
        f"/api/v1/providers/{provider.id}/reviews/summary",
        headers={"Authorization": cust_token},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["provider_id"] == str(provider.id)
    assert data["review_count"] == 0
    assert data["average_rating"] == 0.0
    assert data["rating_distribution"] == {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 0,
        "5": 0,
    }


def test_provider_review_summary_nonexistent_and_invalid_role(
    client: TestClient, db: Session
) -> None:
    """Verify summary returns 404 for nonexistent user and 400 for non-provider user."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    fake_provider_id = str(uuid.uuid4())

    # Nonexistent user -> 404
    res_404 = client.get(
        f"/api/v1/providers/{fake_provider_id}/reviews/summary",
        headers={"Authorization": cust_token},
    )
    assert res_404.status_code == status.HTTP_404_NOT_FOUND
    assert "Provider not found" in res_404.json()["detail"]

    # Target user is a customer, not a provider -> 400
    res_400 = client.get(
        f"/api/v1/providers/{customer.id}/reviews/summary",
        headers={"Authorization": cust_token},
    )
    assert res_400.status_code == status.HTTP_400_BAD_REQUEST
    assert "not registered as a service provider" in res_400.json()["detail"]
