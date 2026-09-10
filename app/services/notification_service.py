import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.enums import NotificationType
from app.models.notification import Notification


def create_notification(
    db: Session,
    *,
    user_id: uuid.UUID,
    type: NotificationType,
    title: str,
    message: str,
    booking_id: uuid.UUID | None = None,
) -> Notification | None:
    """Create a persistent notification with database-level idempotency.

    Uses PostgreSQL's atomic ON CONFLICT DO NOTHING against the
    uq_notifications_user_booking_type unique constraint.

    If a notification for (user_id, booking_id, type) already exists:
    - Does NOT raise an IntegrityError
    - Does NOT poison the session / surrounding transaction
    - Does NOT create a duplicate notification
    - Returns None safely
    """
    stmt = (
        insert(Notification)
        .values(
            user_id=user_id,
            booking_id=booking_id,
            type=type,
            title=title,
            message=message,
        )
        .on_conflict_do_nothing(
            constraint="uq_notifications_user_booking_type",
        )
        .returning(Notification)
    )
    result = db.execute(stmt).scalars().first()
    return result


def list_notifications(
    db: Session,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
    unread_only: bool = False,
) -> list[Notification]:
    """List notifications strictly scoped to user_id, ordered by created_at desc."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
    return list(db.execute(stmt).scalars().all())


def mark_notification_as_read(
    db: Session,
    notification_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Notification:
    """Mark a specific notification as read.

    Rules:
    - nonexistent -> 404
    - another user's notification -> 403
    - own notification -> mark read, set read_at, idempotent if already read
    """
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    if notification.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this notification",
        )

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(notification)

    return notification


def mark_all_as_read(
    db: Session,
    user_id: uuid.UUID,
) -> int:
    """Mark all unread notifications for user_id as read.

    Returns the number of notifications updated.
    """
    now = datetime.now(UTC)
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        .values(
            is_read=True,
            read_at=now,
        )
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount
