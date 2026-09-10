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


class NotificationType(enum.StrEnum):
    """Notification type classification."""

    BOOKING_CREATED = "booking_created"
    BOOKING_CONFIRMED = "booking_confirmed"
    BOOKING_CANCELLED = "booking_cancelled"
    BOOKING_REMINDER = "booking_reminder"
    BOOKING_COMPLETED = "booking_completed"
    BOOKING_OVERDUE = "booking_overdue"
