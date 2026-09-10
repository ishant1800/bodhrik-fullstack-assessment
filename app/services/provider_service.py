import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.user import User
from app.schemas.provider import ProviderAvailabilityResponse


def list_providers(
    db: Session,
    search: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> list[User]:
    """Retrieve paginated list of service providers, with optional search filter."""
    stmt = select(User).where(User.role == UserRole.PROVIDER)

    if search is not None and search.strip():
        search_pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern),
            )
        )

    stmt = stmt.order_by(User.name.asc()).offset(skip).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_provider_by_id(
    db: Session,
    provider_id: uuid.UUID,
) -> User:
    """Retrieve a single service provider by ID, validating role."""
    provider = db.get(User, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    if provider.role != UserRole.PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected user is not registered as a service provider",
        )

    return provider


def is_provider_available(
    db: Session,
    provider_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: uuid.UUID | None = None,
) -> bool:
    """Check whether a provider is free from active booking conflicts for a time slot.

    Uses an efficient SQL existence check against PostgreSQL.
    Active bookings include PENDING, CONFIRMED, and COMPLETED.
    CANCELLED bookings are explicitly excluded.
    Adjacent bookings are permitted (start == existing.end or end == existing.start).
    """
    stmt = select(Booking.id).where(
        Booking.provider_id == provider_id,
        Booking.status != BookingStatus.CANCELLED,
        Booking.start_time < end_time,
        Booking.end_time > start_time,
    )
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)

    conflict = db.execute(stmt.limit(1)).first()
    return conflict is None


def check_provider_availability(
    db: Session,
    provider_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
) -> ProviderAvailabilityResponse:
    """Determine provider availability for a requested time range."""
    # 1. Validate that the provider exists and holds PROVIDER role
    get_provider_by_id(db=db, provider_id=provider_id)

    # 2. Check for active booking overlap
    available = is_provider_available(
        db=db,
        provider_id=provider_id,
        start_time=start_time,
        end_time=end_time,
    )

    return ProviderAvailabilityResponse(
        provider_id=provider_id,
        start_time=start_time,
        end_time=end_time,
        available=available,
    )
