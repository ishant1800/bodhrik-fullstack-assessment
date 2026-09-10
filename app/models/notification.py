import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import NotificationType

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.user import User


class Notification(Base):
    """Notification entity recording alerts and messages delivered to users."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "booking_id",
            "type",
            name="uq_notifications_user_booking_type",
        ),
        Index("ix_notifications_user_is_read", "user_id", "is_read"),
        Index("ix_notifications_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    type: Mapped[NotificationType] = mapped_column(
        SAEnum(
            NotificationType,
            name="notification_type",
            values_callable=lambda x: [e.value for e in x],
            native_enum=True,
        ),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="notifications",
    )
    booking: Mapped[Optional["Booking"]] = relationship(
        "Booking",
        back_populates="notifications",
    )
