import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.enums import BookingStatus, NotificationType, UserRole
from app.models.user import User
from app.schemas.booking import BookingCreate, BookingUpdate
from app.services.notification_service import create_notification
from app.services.provider_service import is_provider_available

# ---------------------------------------------------------------------------
# Centralized Status Transition Rules
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PENDING: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.COMPLETED, BookingStatus.CANCELLED},
    BookingStatus.COMPLETED: set(),
    BookingStatus.CANCELLED: set(),
}

ROLE_ALLOWED_TRANSITIONS: dict[tuple[BookingStatus, BookingStatus], set[UserRole]] = {
    (BookingStatus.PENDING, BookingStatus.CONFIRMED): {
        UserRole.PROVIDER,
        UserRole.ADMIN,
    },
    (BookingStatus.PENDING, BookingStatus.CANCELLED): {
        UserRole.CUSTOMER,
        UserRole.PROVIDER,
        UserRole.ADMIN,
    },
    (BookingStatus.CONFIRMED, BookingStatus.COMPLETED): {
        UserRole.PROVIDER,
        UserRole.ADMIN,
    },
    (BookingStatus.CONFIRMED, BookingStatus.CANCELLED): {
        UserRole.CUSTOMER,
        UserRole.PROVIDER,
        UserRole.ADMIN,
    },
}


def _notify_cancellation(db: Session, booking: Booking, actor: User) -> None:
    """Notify affected non-actor participants of a booking cancellation."""
    message = f"Booking for {booking.service_name} has been cancelled."
    if actor.id != booking.customer_id:
        create_notification(
            db=db,
            user_id=booking.customer_id,
            booking_id=booking.id,
            type=NotificationType.BOOKING_CANCELLED,
            title="Booking Cancelled",
            message=message,
        )
    if actor.id != booking.provider_id:
        create_notification(
            db=db,
            user_id=booking.provider_id,
            booking_id=booking.id,
            type=NotificationType.BOOKING_CANCELLED,
            title="Booking Cancelled",
            message=message,
        )


def validate_status_transition(
    current_status: BookingStatus,
    target_status: BookingStatus,
    user_role: UserRole,
) -> None:
    """Validate that a requested status transition adheres to business rules.

    Raises:
        HTTPException 400: If the booking is in a terminal state or the transition
                           is not allowed by the state machine.
        HTTPException 403: If the user's role does not allow this transition.
    """
    if current_status == BookingStatus.CANCELLED:
        if target_status == BookingStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Booking is already cancelled",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify a cancelled booking",
        )

    if current_status == BookingStatus.COMPLETED:
        if target_status == BookingStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel an already completed booking",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify a completed booking",
        )

    if target_status == current_status:
        return

    allowed_targets = VALID_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot transition booking status from "
                f"'{current_status.value}' to '{target_status.value}'"
            ),
        )

    allowed_roles = ROLE_ALLOWED_TRANSITIONS.get((current_status, target_status), set())
    if user_role not in allowed_roles:
        if user_role == UserRole.CUSTOMER and target_status in (
            BookingStatus.CONFIRMED,
            BookingStatus.COMPLETED,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers are not permitted to confirm or complete bookings",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to execute this status transition",
        )


def check_provider_conflict(
    db: Session,
    provider_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: uuid.UUID | None = None,
) -> None:
    """Verify provider has no active overlapping bookings.

    Overlap: existing.start < requested.end AND existing.end > requested.start.
    Cancelled bookings are explicitly excluded.

    Raises:
        HTTPException 409: If an active overlapping booking exists.
    """
    if not is_provider_available(
        db=db,
        provider_id=provider_id,
        start_time=start_time,
        end_time=end_time,
        exclude_booking_id=exclude_booking_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider has an overlapping booking for the requested time slot",
        )


def create_booking(
    db: Session,
    customer_id: uuid.UUID,
    booking_in: BookingCreate,
) -> Booking:
    """Create a new booking reservation for the authenticated customer."""
    # 1. Customer cannot book themselves
    if customer_id == booking_in.provider_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer cannot book themselves as a provider",
        )

    # 2. Check provider exists
    provider = db.get(User, booking_in.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    # 3. Check provider has PROVIDER role
    if provider.role != UserRole.PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected user is not registered as a service provider",
        )

    # 4. Check for active schedule conflicts for the provider
    check_provider_conflict(
        db=db,
        provider_id=booking_in.provider_id,
        start_time=booking_in.start_time,
        end_time=booking_in.end_time,
    )

    # 5. Create and persist booking
    booking = Booking(
        customer_id=customer_id,
        provider_id=booking_in.provider_id,
        service_name=booking_in.service_name,
        start_time=booking_in.start_time,
        end_time=booking_in.end_time,
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.flush()

    # Booking created lifecycle notification -> provider
    create_notification(
        db=db,
        user_id=booking.provider_id,
        booking_id=booking.id,
        type=NotificationType.BOOKING_CREATED,
        title="New Booking Request",
        message=f"A new booking request for {booking.service_name} has been submitted.",
    )

    try:
        db.commit()
        db.refresh(booking)
        return booking
    except Exception:
        db.rollback()
        raise


def get_booking_by_id(
    db: Session,
    booking_id: uuid.UUID,
    current_user: User,
) -> Booking:
    """Retrieve a single booking by ID with ownership-based authorization."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    # Authorization check
    if current_user.role == UserRole.ADMIN:
        return booking
    if (
        current_user.role == UserRole.CUSTOMER
        and booking.customer_id == current_user.id
    ):
        return booking
    if (
        current_user.role == UserRole.PROVIDER
        and booking.provider_id == current_user.id
    ):
        return booking

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access this booking",
    )


def list_bookings(
    db: Session,
    current_user: User,
    status_filter: BookingStatus | None = None,
    skip: int = 0,
    limit: int = 20,
) -> list[Booking]:
    """List bookings filtered by user role and optional status."""
    stmt = select(Booking)

    if current_user.role == UserRole.CUSTOMER:
        stmt = stmt.where(Booking.customer_id == current_user.id)
    elif current_user.role == UserRole.PROVIDER:
        stmt = stmt.where(Booking.provider_id == current_user.id)
    elif current_user.role == UserRole.ADMIN:
        pass  # Admin sees all bookings

    if status_filter is not None:
        stmt = stmt.where(Booking.status == status_filter)

    stmt = (
        stmt.order_by(Booking.start_time.asc(), Booking.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def update_booking(
    db: Session,
    booking_id: uuid.UUID,
    booking_update: BookingUpdate,
    current_user: User,
) -> Booking:
    """Update mutable fields of an existing booking under strict access rules."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    # Authorization check
    is_admin = current_user.role == UserRole.ADMIN
    is_owner_customer = (
        current_user.role == UserRole.CUSTOMER
        and booking.customer_id == current_user.id
    )
    is_assigned_provider = (
        current_user.role == UserRole.PROVIDER
        and booking.provider_id == current_user.id
    )

    if not (is_admin or is_owner_customer or is_assigned_provider):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this booking",
        )

    # Prevent modifications to terminal bookings
    if booking.status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
        if booking_update.status is not None:
            validate_status_transition(
                booking.status, booking_update.status, current_user.role
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot modify a {booking.status.value} booking",
        )

    # 1. Status transition validation
    if booking_update.status is not None and booking_update.status != booking.status:
        validate_status_transition(
            booking.status, booking_update.status, current_user.role
        )
        booking.status = booking_update.status

        # Booking lifecycle notifications on status change
        if booking.status == BookingStatus.CONFIRMED:
            create_notification(
                db=db,
                user_id=booking.customer_id,
                booking_id=booking.id,
                type=NotificationType.BOOKING_CONFIRMED,
                title="Booking Confirmed",
                message=f"Your booking for {booking.service_name} has been confirmed.",
            )
        elif booking.status == BookingStatus.COMPLETED:
            create_notification(
                db=db,
                user_id=booking.customer_id,
                booking_id=booking.id,
                type=NotificationType.BOOKING_COMPLETED,
                title="Booking Completed",
                message=f"Your booking for {booking.service_name} has been completed.",
            )
        elif booking.status == BookingStatus.CANCELLED:
            _notify_cancellation(db=db, booking=booking, actor=current_user)

    # 2. Rescheduling validation
    if booking_update.start_time is not None or booking_update.end_time is not None:
        new_start = booking_update.start_time or booking.start_time
        new_end = booking_update.end_time or booking.end_time

        if new_end <= new_start:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_time must be after start_time",
            )

        check_provider_conflict(
            db=db,
            provider_id=booking.provider_id,
            start_time=new_start,
            end_time=new_end,
            exclude_booking_id=booking.id,
        )
        booking.start_time = new_start
        booking.end_time = new_end

    # 3. Service name update
    if booking_update.service_name is not None:
        booking.service_name = booking_update.service_name

    try:
        db.commit()
        db.refresh(booking)
        return booking
    except Exception:
        db.rollback()
        raise


def cancel_booking(
    db: Session,
    booking_id: uuid.UUID,
    current_user: User,
) -> Booking:
    """Cancel a booking using centralized state machine rules."""
    booking = get_booking_by_id(db=db, booking_id=booking_id, current_user=current_user)

    validate_status_transition(
        current_status=booking.status,
        target_status=BookingStatus.CANCELLED,
        user_role=current_user.role,
    )

    booking.status = BookingStatus.CANCELLED
    _notify_cancellation(db=db, booking=booking, actor=current_user)
    try:
        db.commit()
        db.refresh(booking)
        return booking
    except Exception:
        db.rollback()
        raise
