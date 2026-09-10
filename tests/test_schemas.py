import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.enums import BookingStatus, UserRole
from app.schemas.booking import BookingCreate, BookingUpdate
from app.schemas.review import ReviewCreate
from app.schemas.user import UserResponse

# ============================================================================
# 1. User Schema & Role Validation Tests
# ============================================================================


def test_valid_user_roles() -> None:
    """Verify all valid UserRole values are accepted by the UserResponse schema."""
    now = datetime.now(UTC)
    for role in [UserRole.ADMIN, UserRole.PROVIDER, UserRole.CUSTOMER]:
        user_data = {
            "id": uuid.uuid4(),
            "name": f"Test {role.value}",
            "email": f"{role.value}@example.com",
            "role": role.value,
            "created_at": now,
            "updated_at": now,
        }
        user = UserResponse(**user_data)
        assert user.role == role


def test_invalid_user_role() -> None:
    """Verify that an unrecognized user role raises a ValidationError."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as exc_info:
        UserResponse(
            id=uuid.uuid4(),
            name="Invalid User",
            email="invalid@example.com",
            role="superadmin",  # Invalid role
            created_at=now,
            updated_at=now,
        )
    assert "role" in str(exc_info.value)


# ============================================================================
# 2. Booking Schema & Business Rule Validation Tests
# ============================================================================


def test_booking_create_valid() -> None:
    """Verify a valid BookingCreate payload is accepted."""
    start = datetime.now(UTC) + timedelta(days=1)
    end = start + timedelta(hours=2)

    booking = BookingCreate(
        provider_id=uuid.uuid4(),
        service_name="Deep House Cleaning",
        start_time=start,
        end_time=end,
    )
    assert booking.service_name == "Deep House Cleaning"
    assert booking.end_time > booking.start_time


def test_booking_invalid_time_range_end_before_start() -> None:
    """Verify end_time before start_time raises a validation error."""
    start = datetime.now(UTC) + timedelta(days=1)
    end = start - timedelta(hours=1)  # Invalid: end is before start

    with pytest.raises(ValidationError) as exc_info:
        BookingCreate(
            provider_id=uuid.uuid4(),
            service_name="Service",
            start_time=start,
            end_time=end,
        )
    assert "end_time must be after start_time" in str(exc_info.value)


def test_booking_invalid_time_range_end_equals_start() -> None:
    """Verify end_time equal to start_time raises a validation error."""
    start = datetime.now(UTC) + timedelta(days=1)

    with pytest.raises(ValidationError) as exc_info:
        BookingCreate(
            provider_id=uuid.uuid4(),
            service_name="Service",
            start_time=start,
            end_time=start,  # Zero-length duration
        )
    assert "end_time must be after start_time" in str(exc_info.value)


def test_booking_create_timezone_naive_rejected() -> None:
    """Verify timezone-naive datetimes in BookingCreate raise validation error."""
    naive_start = datetime(2026, 10, 1, 10, 0)
    naive_end = datetime(2026, 10, 1, 12, 0)

    with pytest.raises(ValidationError) as exc_info:
        BookingCreate(
            provider_id=uuid.uuid4(),
            service_name="Service",
            start_time=naive_start,
            end_time=naive_end,
        )
    assert "timezone-aware" in str(exc_info.value)


def test_booking_update_time_range_validation() -> None:
    """Verify BookingUpdate enforces time consistency when both times are updated."""
    start = datetime.now(UTC) + timedelta(days=1)
    end = start - timedelta(hours=1)

    with pytest.raises(ValidationError) as exc_info:
        BookingUpdate(
            start_time=start,
            end_time=end,
            status=BookingStatus.CONFIRMED,
        )
    assert "end_time must be after start_time" in str(exc_info.value)


# ============================================================================
# 3. Review Schema & Validation Tests
# ============================================================================


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_review_create_valid_rating_range(rating: int) -> None:
    """Verify ratings from 1 to 5 are accepted."""
    review = ReviewCreate(
        booking_id=uuid.uuid4(),
        rating=rating,
        comment="Great service!",
    )
    assert review.rating == rating


@pytest.mark.parametrize("invalid_rating", [0, -1, 6, 10])
def test_review_create_invalid_rating(invalid_rating: int) -> None:
    """Verify ratings less than 1 or greater than 5 are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ReviewCreate(
            booking_id=uuid.uuid4(),
            rating=invalid_rating,
        )
    assert "rating" in str(exc_info.value)


def test_review_create_comment_max_length_exceeded() -> None:
    """Verify comment exceeding 2000 characters raises ValidationError."""
    too_long_comment = "a" * 2001
    with pytest.raises(ValidationError) as exc_info:
        ReviewCreate(
            booking_id=uuid.uuid4(),
            rating=5,
            comment=too_long_comment,
        )
    assert "comment" in str(exc_info.value)
