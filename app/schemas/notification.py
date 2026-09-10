from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import NotificationType


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    booking_id: UUID | None
    type: NotificationType
    title: str
    message: str
    is_read: bool
    created_at: datetime
    read_at: datetime | None


class MarkAllReadResponse(BaseModel):
    message: str
    updated_count: int
