from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, check_db_connection, engine
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.review import Review
from app.models.user import User

# Skip PostgreSQL integration tests if the PostgreSQL container is not running
postgres_available = check_db_connection()
pytestmark = pytest.mark.skipif(
    not postgres_available,
    reason="PostgreSQL is not reachable. Start with 'docker compose up -d postgres'.",
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide an isolated database session with automatic transaction rollback."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ============================================================================
# 1. Database Connectivity
# ============================================================================


def test_postgres_connectivity() -> None:
    """Verify application can establish a PostgreSQL connection and run SELECT 1."""
    assert check_db_connection() is True
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1


# ============================================================================
# 2. Schema, Tables, and Enum Verification
# ============================================================================


def test_postgres_tables_exist() -> None:
    """Verify users, bookings, and reviews tables exist in PostgreSQL schema."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "users" in tables
    assert "bookings" in tables
    assert "reviews" in tables


def test_postgres_enums_exist() -> None:
    """Verify user_role and booking_status enums exist with exact expected values."""
    with engine.connect() as conn:
        query = text("""
            SELECT t.typname, e.enumlabel
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            WHERE t.typname IN ('user_role', 'booking_status')
            ORDER BY t.typname, e.enumsortorder;
        """)
        rows = conn.execute(query).fetchall()

    enums_map: dict[str, list[str]] = {}
    for typname, enumlabel in rows:
        enums_map.setdefault(typname, []).append(enumlabel)

    assert "user_role" in enums_map
    assert enums_map["user_role"] == ["admin", "provider", "customer"]

    assert "booking_status" in enums_map
    assert enums_map["booking_status"] == [
        "pending",
        "confirmed",
        "completed",
        "cancelled",
    ]


# ============================================================================
# 3. Foreign Key Constraints
# ============================================================================


def test_postgres_foreign_keys_configured() -> None:
    """Verify foreign key references between bookings, reviews, and users."""
    inspector = inspect(engine)

    # Inspect bookings foreign keys
    booking_fks = inspector.get_foreign_keys("bookings")
    booking_fk_map = {fk["constrained_columns"][0]: fk for fk in booking_fks}

    assert "customer_id" in booking_fk_map
    assert booking_fk_map["customer_id"]["referred_table"] == "users"
    assert booking_fk_map["customer_id"]["referred_columns"] == ["id"]

    assert "provider_id" in booking_fk_map
    assert booking_fk_map["provider_id"]["referred_table"] == "users"
    assert booking_fk_map["provider_id"]["referred_columns"] == ["id"]

    # Inspect reviews foreign keys
    review_fks = inspector.get_foreign_keys("reviews")
    review_fk_map = {fk["constrained_columns"][0]: fk for fk in review_fks}

    assert "booking_id" in review_fk_map
    assert review_fk_map["booking_id"]["referred_table"] == "bookings"
    assert review_fk_map["booking_id"]["referred_columns"] == ["id"]

    assert "customer_id" in review_fk_map
    assert review_fk_map["customer_id"]["referred_table"] == "users"

    assert "provider_id" in review_fk_map
    assert review_fk_map["provider_id"]["referred_table"] == "users"


# ============================================================================
# 4. Check Constraints
# ============================================================================


def test_postgres_enforces_end_time_after_start_time(db_session: Session) -> None:
    """Verify PostgreSQL rejects bookings where end_time <= start_time."""
    customer = User(name="Cust A", email="cust_a@example.com", role=UserRole.CUSTOMER)
    provider = User(name="Prov A", email="prov_a@example.com", role=UserRole.PROVIDER)
    db_session.add_all([customer, provider])
    db_session.flush()

    start = datetime.now(UTC)
    invalid_end = start - timedelta(hours=1)

    invalid_booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name="Cleaning",
        start_time=start,
        end_time=invalid_end,
        status=BookingStatus.PENDING,
    )
    db_session.add(invalid_booking)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "check_booking_end_after_start" in str(exc_info.value).lower()
    db_session.rollback()


def test_postgres_enforces_customer_not_equal_provider(
    db_session: Session,
) -> None:
    """Verify PostgreSQL rejects bookings where customer_id == provider_id."""
    user = User(name="Self User", email="self@example.com", role=UserRole.CUSTOMER)
    db_session.add(user)
    db_session.flush()

    start = datetime.now(UTC)
    end = start + timedelta(hours=2)

    invalid_booking = Booking(
        customer_id=user.id,
        provider_id=user.id,
        service_name="Self Service",
        start_time=start,
        end_time=end,
        status=BookingStatus.PENDING,
    )
    db_session.add(invalid_booking)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "check_booking_customer_not_provider" in str(exc_info.value).lower()
    db_session.rollback()


def test_postgres_enforces_review_rating_bounds(db_session: Session) -> None:
    """Verify PostgreSQL CheckConstraint rejects reviews outside [1, 5]."""
    customer = User(name="Cust B", email="cust_b@example.com", role=UserRole.CUSTOMER)
    provider = User(name="Prov B", email="prov_b@example.com", role=UserRole.PROVIDER)
    db_session.add_all([customer, provider])
    db_session.flush()

    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name="Painting",
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC) + timedelta(hours=1),
        status=BookingStatus.COMPLETED,
    )
    db_session.add(booking)
    db_session.flush()

    # Rating = 0 (below 1)
    rev_low = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=0,
    )
    db_session.add(rev_low)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "check_review_rating_range" in str(exc_info.value).lower()
    db_session.rollback()

    # Re-insert booking after rollback
    db_session.add_all([customer, provider, booking])
    db_session.flush()

    # Rating = 6 (above 5)
    rev_high = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=6,
    )
    db_session.add(rev_high)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert "check_review_rating_range" in str(exc_info.value).lower()


# ============================================================================
# 5. Unique Constraint & Cascade Behavior
# ============================================================================


def test_postgres_enforces_one_review_per_booking(db_session: Session) -> None:
    """Verify PostgreSQL unique constraint rejects duplicate review for same booking."""
    customer = User(name="Cust C", email="cust_c@example.com", role=UserRole.CUSTOMER)
    provider = User(name="Prov C", email="prov_c@example.com", role=UserRole.PROVIDER)
    db_session.add_all([customer, provider])
    db_session.flush()

    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name="Gardening",
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC) + timedelta(hours=1),
        status=BookingStatus.COMPLETED,
    )
    db_session.add(booking)
    db_session.flush()

    first_rev = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=5,
        comment="First review",
    )
    db_session.add(first_rev)
    db_session.flush()

    second_rev = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=4,
        comment="Second review - must fail",
    )
    db_session.add(second_rev)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_postgres_cascade_delete_booking_deletes_review(
    db_session: Session,
) -> None:
    """Verify deleting a booking cascades to automatically delete its review."""
    customer = User(name="Cust D", email="cust_d@example.com", role=UserRole.CUSTOMER)
    provider = User(name="Prov D", email="prov_d@example.com", role=UserRole.PROVIDER)
    db_session.add_all([customer, provider])
    db_session.flush()

    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name="Tutoring",
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC) + timedelta(hours=1),
        status=BookingStatus.COMPLETED,
    )
    db_session.add(booking)
    db_session.flush()

    review = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=5,
    )
    db_session.add(review)
    db_session.flush()

    # Delete booking directly in database
    db_session.delete(booking)
    db_session.flush()

    # Review must be gone
    deleted_review = db_session.get(Review, review.id)
    assert deleted_review is None


def test_postgres_cascade_delete_user_deletes_bookings_and_reviews(
    db_session: Session,
) -> None:
    """Verify deleting a customer cascades to delete their bookings and reviews."""
    customer = User(name="Cust E", email="cust_e@example.com", role=UserRole.CUSTOMER)
    provider = User(name="Prov E", email="prov_e@example.com", role=UserRole.PROVIDER)
    db_session.add_all([customer, provider])
    db_session.flush()

    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name="Carpentry",
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC) + timedelta(hours=2),
        status=BookingStatus.COMPLETED,
    )
    db_session.add(booking)
    db_session.flush()

    review = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=4,
    )
    db_session.add(review)
    db_session.flush()

    # Delete customer
    db_session.delete(customer)
    db_session.flush()

    assert db_session.get(Booking, booking.id) is None
    assert db_session.get(Review, review.id) is None
