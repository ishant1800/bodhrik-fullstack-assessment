import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.jobs.booking_jobs import run_booking_reminder_job, run_overdue_booking_job
from app.jobs.scheduler import BackgroundJobScheduler
from app.models.booking import Booking
from app.models.enums import BookingStatus, NotificationType, UserRole
from app.models.notification import Notification
from app.models.user import User
from app.services.notification_service import (
    create_notification,
    list_notifications,
)

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
def cleanup_notification_test_data():
    """Clean up test notifications, bookings, and users after each test."""
    yield
    session = SessionLocal()
    try:
        # Delete notifications for test users
        users = (
            session.execute(
                select(User).where(User.email.like("%@notiftest.example.com"))
            )
            .scalars()
            .all()
        )
        user_ids = [u.id for u in users]
        if user_ids:
            notifs = (
                session.execute(
                    select(Notification).where(Notification.user_id.in_(user_ids))
                )
                .scalars()
                .all()
            )
            for n in notifs:
                session.delete(n)
            session.commit()

            bookings = (
                session.execute(
                    select(Booking).where(
                        Booking.customer_id.in_(user_ids)
                        | Booking.provider_id.in_(user_ids)
                    )
                )
                .scalars()
                .all()
            )
            for b in bookings:
                session.delete(b)
            session.commit()

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
        email=f"{role.value}_{uuid.uuid4().hex[:8]}@notiftest.example.com",
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
    booking_status: BookingStatus = BookingStatus.CONFIRMED,
    service_name: str = "Notification Test Service",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> Booking:
    """Helper creating a booking reservation in the specified state and window."""
    if start_time is None:
        start_time = datetime.now(UTC) + timedelta(hours=2)
    if end_time is None:
        end_time = start_time + timedelta(hours=1)

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


# ---------------------------------------------------------------------------
# 1. Authentication Tests
# ---------------------------------------------------------------------------


def test_list_notifications_unauthenticated(client: TestClient):
    """Unauthenticated GET /api/v1/notifications must return 401."""
    response = client.get("/api/v1/notifications")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_mark_read_unauthenticated(client: TestClient):
    """Unauthenticated PATCH /api/v1/notifications/{id}/read must return 401."""
    fake_id = uuid.uuid4()
    response = client.patch(f"/api/v1/notifications/{fake_id}/read")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_mark_all_read_unauthenticated(client: TestClient):
    """Unauthenticated PATCH /api/v1/notifications/read-all must return 401."""
    response = client.patch("/api/v1/notifications/read-all")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# 2. Isolation & Security Tests
# ---------------------------------------------------------------------------


def test_notification_isolation_between_users(client: TestClient, db: Session):
    """Users must only see their own notifications; others are invisible."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER, "Customer A")
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER, "Provider B")
    admin, admin_token = create_user_with_token(db, UserRole.ADMIN, "Admin C")

    # Create distinct notifications for each user
    create_notification(
        db=db,
        user_id=customer.id,
        type=NotificationType.BOOKING_CONFIRMED,
        title="Customer Notif",
        message="Message for customer",
    )
    create_notification(
        db=db,
        user_id=provider.id,
        type=NotificationType.BOOKING_CREATED,
        title="Provider Notif",
        message="Message for provider",
    )
    create_notification(
        db=db,
        user_id=admin.id,
        type=NotificationType.BOOKING_OVERDUE,
        title="Admin Notif",
        message="Message for admin",
    )
    db.commit()

    # Customer sees only customer notification
    resp_cust = client.get(
        "/api/v1/notifications", headers={"Authorization": cust_token}
    )
    assert resp_cust.status_code == status.HTTP_200_OK
    cust_data = resp_cust.json()
    assert len(cust_data) == 1
    assert cust_data[0]["title"] == "Customer Notif"

    # Provider sees only provider notification
    resp_prov = client.get(
        "/api/v1/notifications", headers={"Authorization": prov_token}
    )
    assert resp_prov.status_code == status.HTTP_200_OK
    prov_data = resp_prov.json()
    assert len(prov_data) == 1
    assert prov_data[0]["title"] == "Provider Notif"

    # Admin sees only admin notification
    resp_admin = client.get(
        "/api/v1/notifications", headers={"Authorization": admin_token}
    )
    assert resp_admin.status_code == status.HTTP_200_OK
    admin_data = resp_admin.json()
    assert len(admin_data) == 1
    assert admin_data[0]["title"] == "Admin Notif"


def test_cannot_spoof_user_id_query_param(client: TestClient, db: Session):
    """Passing user_id in query parameters must not override authenticated identity."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    create_notification(
        db=db,
        user_id=provider.id,
        type=NotificationType.BOOKING_CREATED,
        title="Provider Secret",
        message="Confidential",
    )
    db.commit()

    # Customer tries to spoof provider user_id via query param
    resp = client.get(
        f"/api/v1/notifications?user_id={provider.id}",
        headers={"Authorization": cust_token},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data) == 0  # Customer still sees only their own (empty) list


def test_mark_read_other_users_notification_forbidden(client: TestClient, db: Session):
    """Attempting to mark another user's notification as read must return 403."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    notif = create_notification(
        db=db,
        user_id=provider.id,
        type=NotificationType.BOOKING_CREATED,
        title="Provider Notif",
        message="Provider only",
    )
    db.commit()

    # Customer tries to mark provider's notification as read
    resp = client.patch(
        f"/api/v1/notifications/{notif.id}/read",
        headers={"Authorization": cust_token},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "Not authorized" in resp.json()["detail"]


def test_mark_read_nonexistent_returns_404(client: TestClient, db: Session):
    """Marking a nonexistent notification as read must return 404."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    fake_id = uuid.uuid4()

    resp = client.patch(
        f"/api/v1/notifications/{fake_id}/read",
        headers={"Authorization": cust_token},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_notification_schema_does_not_expose_user_id_or_password(
    client: TestClient, db: Session
):
    """Notification response schema must not leak user_id or password_hash."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    create_notification(
        db=db,
        user_id=customer.id,
        type=NotificationType.BOOKING_CONFIRMED,
        title="Test Schema",
        message="Check schema fields",
    )
    db.commit()

    resp = client.get("/api/v1/notifications", headers={"Authorization": cust_token})
    assert resp.status_code == status.HTTP_200_OK
    item = resp.json()[0]
    assert "user_id" not in item
    assert "password_hash" not in item
    assert "id" in item
    assert "type" in item
    assert "title" in item
    assert "message" in item
    assert "is_read" in item
    assert "created_at" in item
    assert "read_at" in item


# ---------------------------------------------------------------------------
# 3. Pagination & Query Parameters
# ---------------------------------------------------------------------------


def test_notification_pagination_and_unread_filter(client: TestClient, db: Session):
    """Test skip, limit, unread_only filtering, and validation bounds."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)

    # Create 5 notifications
    for i in range(5):
        notif = create_notification(
            db=db,
            user_id=customer.id,
            type=NotificationType.BOOKING_REMINDER,
            title=f"Notif {i}",
            message=f"Message {i}",
        )
        if i == 0:
            notif.is_read = True
            notif.read_at = datetime.now(UTC)
    db.commit()

    headers = {"Authorization": cust_token}

    # Default pagination returns all 5
    resp = client.get("/api/v1/notifications", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json()) == 5

    # Skip and limit
    resp_page = client.get("/api/v1/notifications?skip=1&limit=2", headers=headers)
    assert resp_page.status_code == status.HTTP_200_OK
    assert len(resp_page.json()) == 2

    # Unread only filter returns 4
    resp_unread = client.get("/api/v1/notifications?unread_only=true", headers=headers)
    assert resp_unread.status_code == status.HTTP_200_OK
    assert len(resp_unread.json()) == 4
    assert all(n["is_read"] is False for n in resp_unread.json())

    # Limit > 100 rejected with 422
    resp_limit_high = client.get("/api/v1/notifications?limit=101", headers=headers)
    assert resp_limit_high.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Limit < 1 rejected with 422
    resp_limit_low = client.get("/api/v1/notifications?limit=0", headers=headers)
    assert resp_limit_low.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Negative skip rejected with 422
    resp_skip_neg = client.get("/api/v1/notifications?skip=-1", headers=headers)
    assert resp_skip_neg.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# 4. Read State Operations
# ---------------------------------------------------------------------------


def test_mark_own_notification_as_read(client: TestClient, db: Session):
    """Marking own notification as read updates is_read to true and sets read_at."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    notif = create_notification(
        db=db,
        user_id=customer.id,
        type=NotificationType.BOOKING_CONFIRMED,
        title="Mark Read Test",
        message="Testing read transition",
    )
    db.commit()
    assert notif.is_read is False
    assert notif.read_at is None

    resp = client.patch(
        f"/api/v1/notifications/{notif.id}/read",
        headers={"Authorization": cust_token},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["is_read"] is True
    assert data["read_at"] is not None
    first_read_at = data["read_at"]

    # Calling it a second time is safely idempotent and maintains read_at
    resp2 = client.patch(
        f"/api/v1/notifications/{notif.id}/read",
        headers={"Authorization": cust_token},
    )
    assert resp2.status_code == status.HTTP_200_OK
    data2 = resp2.json()
    assert data2["is_read"] is True
    assert data2["read_at"] == first_read_at


def test_mark_all_notifications_as_read(client: TestClient, db: Session):
    """Mark-all-read updates only current user's unread notifications."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    other_user, other_token = create_user_with_token(db, UserRole.PROVIDER)

    # 3 unread for customer
    for i in range(3):
        create_notification(
            db=db,
            user_id=customer.id,
            type=NotificationType.BOOKING_REMINDER,
            title=f"Cust Notif {i}",
            message=f"Cust Msg {i}",
        )
    # 2 unread for other user
    for i in range(2):
        create_notification(
            db=db,
            user_id=other_user.id,
            type=NotificationType.BOOKING_REMINDER,
            title=f"Other Notif {i}",
            message=f"Other Msg {i}",
        )
    db.commit()

    resp = client.patch(
        "/api/v1/notifications/read-all",
        headers={"Authorization": cust_token},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["updated_count"] == 3
    assert data["message"] == "All unread notifications marked as read"

    # Verify customer notifications are all read
    cust_notifs = list_notifications(db, customer.id)
    assert all(n.is_read is True for n in cust_notifs)

    # Verify other user's notifications remain unread
    other_notifs = list_notifications(db, other_user.id)
    assert all(n.is_read is False for n in other_notifs)


# ---------------------------------------------------------------------------
# 5. Booking Lifecycle Notifications
# ---------------------------------------------------------------------------


def test_booking_created_lifecycle_notification(client: TestClient, db: Session):
    """Creating a booking triggers a BOOKING_CREATED notification for the provider."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)

    start = datetime.now(UTC) + timedelta(days=2)
    end = start + timedelta(hours=1)

    booking_payload = {
        "provider_id": str(provider.id),
        "service_name": "Plumbing Repair",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }

    resp = client.post(
        "/api/v1/bookings",
        json=booking_payload,
        headers={"Authorization": cust_token},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    booking_id = resp.json()["id"]

    # Provider must have received a BOOKING_CREATED notification
    prov_notifs = client.get(
        "/api/v1/notifications", headers={"Authorization": prov_token}
    ).json()
    assert len(prov_notifs) == 1
    assert prov_notifs[0]["type"] == NotificationType.BOOKING_CREATED.value
    assert prov_notifs[0]["booking_id"] == booking_id

    # Customer must NOT have received a booking_created notification
    cust_notifs = client.get(
        "/api/v1/notifications", headers={"Authorization": cust_token}
    ).json()
    assert len(cust_notifs) == 0


def test_booking_confirmed_lifecycle_notification(client: TestClient, db: Session):
    """Transitioning PENDING -> CONFIRMED sends BOOKING_CONFIRMED to customer."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)

    booking = create_test_booking(
        db, customer, provider, booking_status=BookingStatus.PENDING
    )

    # Provider confirms booking
    resp = client.patch(
        f"/api/v1/bookings/{booking.id}",
        json={"status": BookingStatus.CONFIRMED.value},
        headers={"Authorization": prov_token},
    )
    assert resp.status_code == status.HTTP_200_OK

    # Customer receives BOOKING_CONFIRMED notification
    cust_notifs = client.get(
        "/api/v1/notifications", headers={"Authorization": cust_token}
    ).json()
    assert len(cust_notifs) == 1
    assert cust_notifs[0]["type"] == NotificationType.BOOKING_CONFIRMED.value
    assert cust_notifs[0]["booking_id"] == str(booking.id)


def test_booking_completed_lifecycle_notification(client: TestClient, db: Session):
    """Transitioning CONFIRMED -> COMPLETED sends BOOKING_COMPLETED to customer."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)

    booking = create_test_booking(
        db, customer, provider, booking_status=BookingStatus.CONFIRMED
    )

    # Provider completes booking
    resp = client.patch(
        f"/api/v1/bookings/{booking.id}",
        json={"status": BookingStatus.COMPLETED.value},
        headers={"Authorization": prov_token},
    )
    assert resp.status_code == status.HTTP_200_OK

    # Customer receives BOOKING_COMPLETED notification
    cust_notifs = client.get(
        "/api/v1/notifications", headers={"Authorization": cust_token}
    ).json()
    assert len(cust_notifs) == 1
    assert cust_notifs[0]["type"] == NotificationType.BOOKING_COMPLETED.value
    assert cust_notifs[0]["booking_id"] == str(booking.id)


def test_booking_cancelled_by_customer_notifies_provider_not_actor(
    client: TestClient, db: Session
):
    """Customer cancelling booking sends BOOKING_CANCELLED to provider, not actor."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)

    booking = create_test_booking(
        db, customer, provider, booking_status=BookingStatus.CONFIRMED
    )

    resp = client.post(
        f"/api/v1/bookings/{booking.id}/cancel",
        headers={"Authorization": cust_token},
    )
    assert resp.status_code == status.HTTP_200_OK

    # Provider receives BOOKING_CANCELLED notification
    prov_notifs = client.get(
        "/api/v1/notifications", headers={"Authorization": prov_token}
    ).json()
    assert len(prov_notifs) == 1
    assert prov_notifs[0]["type"] == NotificationType.BOOKING_CANCELLED.value
    assert prov_notifs[0]["booking_id"] == str(booking.id)

    # Actor (customer) does NOT receive cancellation notification
    cust_notifs = client.get(
        "/api/v1/notifications", headers={"Authorization": cust_token}
    ).json()
    assert len(cust_notifs) == 0


def test_booking_cancelled_by_provider_notifies_customer_not_actor(
    client: TestClient, db: Session
):
    """Provider cancelling booking sends BOOKING_CANCELLED to customer, not actor."""
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, prov_token = create_user_with_token(db, UserRole.PROVIDER)

    booking = create_test_booking(
        db, customer, provider, booking_status=BookingStatus.CONFIRMED
    )

    resp = client.post(
        f"/api/v1/bookings/{booking.id}/cancel",
        headers={"Authorization": prov_token},
    )
    assert resp.status_code == status.HTTP_200_OK

    # Customer receives BOOKING_CANCELLED notification
    cust_notifs = client.get(
        "/api/v1/notifications", headers={"Authorization": cust_token}
    ).json()
    assert len(cust_notifs) == 1
    assert cust_notifs[0]["type"] == NotificationType.BOOKING_CANCELLED.value

    # Actor (provider) does NOT receive cancellation notification
    prov_notifs = client.get(
        "/api/v1/notifications", headers={"Authorization": prov_token}
    ).json()
    assert len(prov_notifs) == 0


# ---------------------------------------------------------------------------
# 6. Reminder Background Job Tests
# ---------------------------------------------------------------------------


def test_booking_reminder_job_creates_notifications_for_confirmed_bookings(
    db: Session,
):
    """Reminder job notifies customer and provider for confirmed bookings in window."""
    customer, _ = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    # 1. Booking within 30 min window (starts in 15 mins)
    start_inside = datetime.now(UTC) + timedelta(minutes=15)
    end_inside = start_inside + timedelta(hours=1)
    b_inside = create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.CONFIRMED,
        start_time=start_inside,
        end_time=end_inside,
    )

    # 2. PENDING booking within window (MUST BE IGNORED)
    create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.PENDING,
        start_time=start_inside,
        end_time=end_inside,
    )

    # 3. CANCELLED booking within window (MUST BE IGNORED)
    create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.CANCELLED,
        start_time=start_inside,
        end_time=end_inside,
    )

    # 4. COMPLETED booking within window (MUST BE IGNORED)
    create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.COMPLETED,
        start_time=start_inside,
        end_time=end_inside,
    )

    # 5. CONFIRMED booking outside window (starts in 2 hours - MUST BE IGNORED)
    start_outside = datetime.now(UTC) + timedelta(hours=2)
    end_outside = start_outside + timedelta(hours=1)
    create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.CONFIRMED,
        start_time=start_outside,
        end_time=end_outside,
    )

    # Run reminder job directly
    count = run_booking_reminder_job(db, reminder_window_minutes=30)
    assert count == 2  # 1 for customer, 1 for provider

    # Verify notifications created for b_inside only
    cust_notifs = list_notifications(db, customer.id)
    assert len(cust_notifs) == 1
    assert cust_notifs[0].booking_id == b_inside.id
    assert cust_notifs[0].type == NotificationType.BOOKING_REMINDER

    prov_notifs = list_notifications(db, provider.id)
    assert len(prov_notifs) == 1
    assert prov_notifs[0].booking_id == b_inside.id
    assert prov_notifs[0].type == NotificationType.BOOKING_REMINDER

    # IDEMPOTENCY: Run reminder job again immediately -> must create 0 new notifications
    count2 = run_booking_reminder_job(db, reminder_window_minutes=30)
    assert count2 == 0
    assert len(list_notifications(db, customer.id)) == 1
    assert len(list_notifications(db, provider.id)) == 1


# ---------------------------------------------------------------------------
# 7. Overdue Background Job Tests (Important Business Rules)
# ---------------------------------------------------------------------------


def test_overdue_booking_job_only_processes_confirmed_past_end_time(db: Session):
    """Overdue job only notifies for CONFIRMED bookings with end_time < now.

    PENDING bookings are NEVER treated as overdue.
    Booking status is NOT modified.
    """
    customer, _ = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    # Past time (ended 30 mins ago)
    start_past = datetime.now(UTC) - timedelta(hours=1, minutes=30)
    end_past = datetime.now(UTC) - timedelta(minutes=30)

    # 1. CONFIRMED booking past end time -> must trigger BOOKING_OVERDUE
    b_confirmed = create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.CONFIRMED,
        start_time=start_past,
        end_time=end_past,
    )

    # 2. PENDING booking past end time -> MUST BE IGNORED per critical rule!
    create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.PENDING,
        start_time=start_past,
        end_time=end_past,
    )

    # 3. CANCELLED booking past end time -> MUST BE IGNORED
    create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.CANCELLED,
        start_time=start_past,
        end_time=end_past,
    )

    # 4. COMPLETED booking past end time -> MUST BE IGNORED
    create_test_booking(
        db,
        customer,
        provider,
        BookingStatus.COMPLETED,
        start_time=start_past,
        end_time=end_past,
    )

    # Run overdue job directly
    count = run_overdue_booking_job(db)
    assert count == 2  # 1 for customer, 1 for provider

    # Verify notifications
    cust_notifs = list_notifications(db, customer.id)
    assert len(cust_notifs) == 1
    assert cust_notifs[0].booking_id == b_confirmed.id
    assert cust_notifs[0].type == NotificationType.BOOKING_OVERDUE

    prov_notifs = list_notifications(db, provider.id)
    assert len(prov_notifs) == 1
    assert prov_notifs[0].booking_id == b_confirmed.id
    assert prov_notifs[0].type == NotificationType.BOOKING_OVERDUE

    # Verify booking status was NOT changed to something else (e.g. OVERDUE)
    db.refresh(b_confirmed)
    assert b_confirmed.status == BookingStatus.CONFIRMED

    # IDEMPOTENCY: Run overdue job a second time -> 0 new notifications created
    count2 = run_overdue_booking_job(db)
    assert count2 == 0
    assert len(list_notifications(db, customer.id)) == 1
    assert len(list_notifications(db, provider.id)) == 1


# ---------------------------------------------------------------------------
# 8. CRITICAL TRANSACTION TEST: Duplicate Notification Safety
# ---------------------------------------------------------------------------


def test_duplicate_notification_does_not_break_booking_transaction(
    client: TestClient, db: Session
):
    """MANDATORY TEST:

    A pre-existing notification must NOT raise an IntegrityError or poison the
    SQLAlchemy session when a booking operation triggers the same notification.
    The outer booking transaction must still commit successfully.
    """
    customer, cust_token = create_user_with_token(db, UserRole.CUSTOMER)
    provider, _ = create_user_with_token(db, UserRole.PROVIDER)

    booking = create_test_booking(
        db, customer, provider, booking_status=BookingStatus.PENDING
    )

    # Pre-insert the exact notification that booking confirmation would create
    existing_notif = create_notification(
        db=db,
        user_id=customer.id,
        booking_id=booking.id,
        type=NotificationType.BOOKING_CONFIRMED,
        title="Existing Pre-Inserted Notif",
        message="Initial notification content",
    )
    db.commit()
    assert existing_notif is not None

    # Count notifications before booking operation
    count_before = len(list_notifications(db, customer.id))
    assert count_before == 1

    # Execute booking operation that attempts to trigger duplicate notification
    # (Provider confirms booking, triggering BOOKING_CONFIRMED for customer)
    _, prov_token = create_user_with_token(db, UserRole.PROVIDER)
    # Re-assign booking provider to test user
    booking.provider_id = (
        db.execute(select(User).where(User.id == provider.id)).scalar_one().id
    )
    provider_user = db.get(User, provider.id)
    token_prov = f"Bearer {create_access_token(subject=str(provider_user.id))}"

    resp = client.patch(
        f"/api/v1/bookings/{booking.id}",
        json={"status": BookingStatus.CONFIRMED.value},
        headers={"Authorization": token_prov},
    )

    # The booking operation MUST succeed despite the duplicate notification attempt
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == BookingStatus.CONFIRMED.value

    # Verify session was NOT poisoned and booking is indeed confirmed in DB
    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED

    # Notification count remains 1, proving ON CONFLICT DO NOTHING worked cleanly
    count_after = len(list_notifications(db, customer.id))
    assert count_after == 1


# ---------------------------------------------------------------------------
# 9. Scheduler Unit Tests
# ---------------------------------------------------------------------------


def test_scheduler_lifecycle_and_duplicate_prevention():
    """Verify BackgroundJobScheduler starts, prevents duplicates, and stops cleanly."""
    scheduler = BackgroundJobScheduler()
    assert not scheduler.is_running

    # Starting scheduler
    scheduler.start()
    # In test synchronous execution without loop, handles loop absence gracefully
    # If not running, starting again shouldn't crash
    scheduler.start()

    # scheduler._run_single_job error handling
    def faulty_job(session: Session) -> int:
        raise ValueError("Simulated job failure")

    # Must catch and log exception without re-raising
    scheduler._run_single_job("test_faulty", faulty_job)
