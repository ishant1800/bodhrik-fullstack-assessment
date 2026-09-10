from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking
from app.models.enums import BookingStatus, NotificationType
from app.services.notification_service import create_notification


def run_booking_reminder_job(
    db: Session,
    reminder_window_minutes: int | None = None,
) -> int:
    """Find upcoming confirmed bookings within reminder window and create notifications.

    Only confirmed bookings scheduled between now and
    (now + reminder_window_minutes) are matched.
    Creates BOOKING_REMINDER notifications for both customer and provider.
    Idempotency is guaranteed by PostgreSQL unique constraint + ON CONFLICT DO NOTHING.

    Returns the count of new notifications created.
    """
    if reminder_window_minutes is None:
        reminder_window_minutes = settings.BOOKING_REMINDER_MINUTES

    now = datetime.now(UTC)
    window_end = now + timedelta(minutes=reminder_window_minutes)

    stmt = select(Booking).where(
        Booking.status == BookingStatus.CONFIRMED,
        Booking.start_time > now,
        Booking.start_time <= window_end,
    )
    bookings = list(db.execute(stmt).scalars().all())

    created_count = 0
    for booking in bookings:
        # Customer reminder
        cust_notif = create_notification(
            db=db,
            user_id=booking.customer_id,
            booking_id=booking.id,
            type=NotificationType.BOOKING_REMINDER,
            title="Upcoming Booking Reminder",
            message=(
                f"Reminder: You have an upcoming booking for {booking.service_name} "
                f"at {booking.start_time.isoformat()}."
            ),
        )
        if cust_notif is not None:
            created_count += 1

        # Provider reminder
        prov_notif = create_notification(
            db=db,
            user_id=booking.provider_id,
            booking_id=booking.id,
            type=NotificationType.BOOKING_REMINDER,
            title="Upcoming Booking Reminder",
            message=(
                f"Reminder: You have an upcoming service for {booking.service_name} "
                f"scheduled at {booking.start_time.isoformat()}."
            ),
        )
        if prov_notif is not None:
            created_count += 1

    db.commit()
    return created_count


def run_overdue_booking_job(db: Session) -> int:
    """Find confirmed bookings that ended before now and create overdue notifications.

    CRITICAL BUSINESS RULES:
    - Only CONFIRMED bookings whose end_time < now are treated as overdue.
    - PENDING bookings are NEVER processed as overdue.
    - Does NOT alter the BookingStatus or invent an OVERDUE enum value.
    - Creates BOOKING_OVERDUE notifications for customer and provider.
    - Idempotency is guaranteed by unique constraint + ON CONFLICT DO NOTHING.

    Returns the count of new notifications created.
    """
    now = datetime.now(UTC)

    stmt = select(Booking).where(
        Booking.status == BookingStatus.CONFIRMED,
        Booking.end_time < now,
    )
    bookings = list(db.execute(stmt).scalars().all())

    created_count = 0
    for booking in bookings:
        # Customer overdue notification
        cust_notif = create_notification(
            db=db,
            user_id=booking.customer_id,
            booking_id=booking.id,
            type=NotificationType.BOOKING_OVERDUE,
            title="Booking Overdue",
            message=(
                f"Your booking for {booking.service_name} ended at "
                f"{booking.end_time.isoformat()} and is overdue."
            ),
        )
        if cust_notif is not None:
            created_count += 1

        # Provider overdue notification
        prov_notif = create_notification(
            db=db,
            user_id=booking.provider_id,
            booking_id=booking.id,
            type=NotificationType.BOOKING_OVERDUE,
            title="Booking Overdue",
            message=(
                f"The booking for {booking.service_name} ended at "
                f"{booking.end_time.isoformat()} and requires completion."
            ),
        )
        if prov_notif is not None:
            created_count += 1

    db.commit()
    return created_count
