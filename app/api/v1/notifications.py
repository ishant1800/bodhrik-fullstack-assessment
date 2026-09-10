import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import MarkAllReadResponse, NotificationResponse
from app.services import notification_service

router = APIRouter()


@router.get(
    "",
    response_model=list[NotificationResponse],
    status_code=status.HTTP_200_OK,
    summary="List notifications for current authenticated user",
)
def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Notification]:
    """Retrieve notifications strictly scoped to the authenticated user."""
    return notification_service.list_notifications(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        unread_only=unread_only,
    )


@router.patch(
    "/read-all",
    response_model=MarkAllReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark all unread notifications as read",
)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarkAllReadResponse:
    """Mark all unread notifications belonging to the current user as read."""
    count = notification_service.mark_all_as_read(db=db, user_id=current_user.id)
    return MarkAllReadResponse(
        message="All unread notifications marked as read",
        updated_count=count,
    )


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark a single notification as read",
)
def mark_notification_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Notification:
    """Mark a notification as read if it belongs to the authenticated user."""
    return notification_service.mark_notification_as_read(
        db=db,
        notification_id=notification_id,
        user_id=current_user.id,
    )
