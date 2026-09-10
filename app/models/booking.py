import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import BookingStatus

if TYPE_CHECKING:
    from app.models.review import Review
    from app.models.user import User


class Booking(Base):
    """Booking entity capturing service reservations between customer and provider."""

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(
            "end_time > start_time",
            name="check_booking_end_after_start",
        ),
        CheckConstraint(
            "customer_id != provider_id",
            name="check_booking_customer_not_provider",
        ),
        Index("ix_bookings_customer_status", "customer_id", "status"),
        Index("ix_bookings_provider_status", "provider_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, name="booking_status", native_enum=True),
        default=BookingStatus.PENDING,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Disambiguated relationships to Users
    customer: Mapped["User"] = relationship(
        "User",
        foreign_keys=[customer_id],
        back_populates="customer_bookings",
    )
    provider: Mapped["User"] = relationship(
        "User",
        foreign_keys=[provider_id],
        back_populates="provider_bookings",
    )

    # One-to-one relationship with Review
    review: Mapped[Optional["Review"]] = relationship(
        "Review",
        back_populates="booking",
        uselist=False,
        cascade="all, delete-orphan",
    )
