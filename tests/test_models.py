from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.review import Review
from app.models.user import User

# ============================================================================
# 1. SQLAlchemy Metadata & Schema Definition Introspection Tests
# ============================================================================


def test_booking_table_check_constraints_defined() -> None:
    """Verify that Booking table metadata defines the required CheckConstraints."""
    constraint_names = {
        c.name for c in Booking.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "check_booking_end_after_start" in constraint_names
    assert "check_booking_customer_not_provider" in constraint_names


def test_review_table_check_constraints_defined() -> None:
    """Verify that Review table metadata defines the rating CheckConstraint."""
    constraint_names = {
        c.name for c in Review.__table__.constraints if isinstance(c, CheckConstraint)
    }
    assert "check_review_rating_range" in constraint_names


def test_review_table_unique_booking_constraint_defined() -> None:
    """Verify that Review enforces at most one review per booking in metadata."""
    # Check either UniqueConstraint or unique=True column flag
    col = Review.__table__.c.booking_id
    has_unique = col.unique or any(
        isinstance(c, UniqueConstraint)
        and "booking_id" in [c_col.name for c_col in c.columns]
        for c in Review.__table__.constraints
    )
    assert has_unique is True, "Review.booking_id must enforce unique constraint"


def test_orm_relationships_disambiguated() -> None:
    """Verify ORM relationships between User, Booking, and Review resolve clearly."""
    # User relationships
    assert hasattr(User, "customer_bookings")
    assert hasattr(User, "provider_bookings")
    assert hasattr(User, "customer_reviews")
    assert hasattr(User, "provider_reviews")

    # Booking relationships
    assert hasattr(Booking, "customer")
    assert hasattr(Booking, "provider")
    assert hasattr(Booking, "review")

    # Review relationships
    assert hasattr(Review, "booking")
    assert hasattr(Review, "customer")
    assert hasattr(Review, "provider")


# ============================================================================
# 2. In-Memory Database Relational Constraint Enforcement Tests
# ============================================================================


@pytest.fixture
def in_memory_db() -> Generator[Session, None, None]:
    """Provide a clean in-memory database session for testing schema constraints."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_db_enforces_booking_end_after_start(in_memory_db: Session) -> None:
    """Verify relational engine rejects bookings where end_time <= start_time."""
    customer = User(
        name="Customer Alice",
        email="alice@example.com",
        role=UserRole.CUSTOMER,
        password_hash="test_password_hash",
    )
    provider = User(
        name="Provider Bob",
        email="bob@example.com",
        role=UserRole.PROVIDER,
        password_hash="test_password_hash",
    )
    in_memory_db.add_all([customer, provider])
    in_memory_db.commit()

    start = datetime.now(UTC)
    invalid_end = start - timedelta(hours=1)

    invalid_booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name="Plumbing",
        start_time=start,
        end_time=invalid_end,
        status=BookingStatus.PENDING,
    )
    in_memory_db.add(invalid_booking)
    with pytest.raises(IntegrityError):
        in_memory_db.commit()
    in_memory_db.rollback()


def test_db_enforces_customer_not_provider(in_memory_db: Session) -> None:
    """Verify relational engine rejects bookings where customer_id == provider_id."""
    user = User(
        name="Solo User",
        email="solo@example.com",
        role=UserRole.CUSTOMER,
        password_hash="test_password_hash",
    )
    in_memory_db.add(user)
    in_memory_db.commit()

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
    in_memory_db.add(invalid_booking)
    with pytest.raises(IntegrityError):
        in_memory_db.commit()
    in_memory_db.rollback()


def test_db_enforces_review_rating_range(in_memory_db: Session) -> None:
    """Verify relational engine rejects reviews with rating outside [1, 5]."""
    customer = User(
        name="Cust",
        email="c@example.com",
        role=UserRole.CUSTOMER,
        password_hash="test_password_hash",
    )
    provider = User(
        name="Prov",
        email="p@example.com",
        role=UserRole.PROVIDER,
        password_hash="test_password_hash",
    )
    in_memory_db.add_all([customer, provider])
    in_memory_db.commit()

    start = datetime.now(UTC)
    end = start + timedelta(hours=1)
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name="Painting",
        start_time=start,
        end_time=end,
        status=BookingStatus.COMPLETED,
    )
    in_memory_db.add(booking)
    in_memory_db.commit()

    # Attempt rating = 0 (below 1)
    invalid_review_low = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=0,
    )
    in_memory_db.add(invalid_review_low)
    with pytest.raises(IntegrityError):
        in_memory_db.commit()
    in_memory_db.rollback()

    # Attempt rating = 6 (above 5)
    invalid_review_high = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=6,
    )
    in_memory_db.add(invalid_review_high)
    with pytest.raises(IntegrityError):
        in_memory_db.commit()
    in_memory_db.rollback()


def test_db_enforces_one_review_per_booking(in_memory_db: Session) -> None:
    """Verify relational engine rejects a second review for the same booking."""
    customer = User(
        name="Cust",
        email="c2@example.com",
        role=UserRole.CUSTOMER,
        password_hash="test_password_hash",
    )
    provider = User(
        name="Prov",
        email="p2@example.com",
        role=UserRole.PROVIDER,
        password_hash="test_password_hash",
    )
    in_memory_db.add_all([customer, provider])
    in_memory_db.commit()

    start = datetime.now(UTC)
    end = start + timedelta(hours=1)
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_name="Gardening",
        start_time=start,
        end_time=end,
        status=BookingStatus.COMPLETED,
    )
    in_memory_db.add(booking)
    in_memory_db.commit()

    # First review succeeds
    first_review = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=5,
        comment="First review - excellent!",
    )
    in_memory_db.add(first_review)
    in_memory_db.commit()

    # Second review for the same booking must fail
    second_review = Review(
        booking_id=booking.id,
        customer_id=customer.id,
        provider_id=provider.id,
        rating=4,
        comment="Duplicate review - should fail",
    )
    in_memory_db.add(second_review)
    with pytest.raises(IntegrityError):
        in_memory_db.commit()
    in_memory_db.rollback()
