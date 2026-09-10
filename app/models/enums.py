import enum


class UserRole(enum.StrEnum):
    """User role enumeration for access control."""

    ADMIN = "admin"
    PROVIDER = "provider"
    CUSTOMER = "customer"


class BookingStatus(enum.StrEnum):
    """Lifecycle status enumeration for a booking."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
