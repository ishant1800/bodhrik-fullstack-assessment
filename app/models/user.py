import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.review import Review


class User(Base):
    """User account model with distinct role classification."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            name="user_role",
            values_callable=lambda x: [e.value for e in x],
            native_enum=True,
        ),
        nullable=False,
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

    # Disambiguated relationships to Bookings
    customer_bookings: Mapped[list["Booking"]] = relationship(
        "Booking",
        foreign_keys="[Booking.customer_id]",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    provider_bookings: Mapped[list["Booking"]] = relationship(
        "Booking",
        foreign_keys="[Booking.provider_id]",
        back_populates="provider",
        cascade="all, delete-orphan",
    )

    # Disambiguated relationships to Reviews
    customer_reviews: Mapped[list["Review"]] = relationship(
        "Review",
        foreign_keys="[Review.customer_id]",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    provider_reviews: Mapped[list["Review"]] = relationship(
        "Review",
        foreign_keys="[Review.provider_id]",
        back_populates="provider",
        cascade="all, delete-orphan",
    )
