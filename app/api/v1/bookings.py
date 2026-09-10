import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.models.user import User
from app.schemas.booking import BookingCreate, BookingResponse, BookingUpdate
from app.services import booking_service

router = APIRouter()


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new service booking",
)
def create_booking(
    booking_in: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Booking:
    """Create a new service booking reservation.

    - **provider_id**: UUID of the service provider (must have role provider)
    - **service_name**: Name of the service
    - **start_time**: Timezone-aware start time
    - **end_time**: Timezone-aware end time (must be after start_time)

    Customer identity is derived exclusively from the authenticated user.
    """
    return booking_service.create_booking(
        db=db,
        customer_id=current_user.id,
        booking_in=booking_in,
    )


@router.get(
    "",
    response_model=list[BookingResponse],
    status_code=status.HTTP_200_OK,
    summary="List bookings visible to current user",
)
def list_bookings(
    status: BookingStatus | None = Query(
        default=None, description="Filter by booking status"
    ),
    skip: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Booking]:
    """List bookings according to user role permissions.

    - **Customer**: Sees only their own bookings
    - **Provider**: Sees only bookings assigned to them
    - **Admin**: Sees all bookings across the platform
    """
    return booking_service.list_bookings(
        db=db,
        current_user=current_user,
        status_filter=status,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a booking by ID",
)
def get_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Booking:
    """Retrieve details of a single booking reservation.

    Access restricted to customer owner, assigned provider, or admin.
    """
    return booking_service.get_booking_by_id(
        db=db,
        booking_id=booking_id,
        current_user=current_user,
    )


@router.patch(
    "/{booking_id}",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a booking",
)
def update_booking(
    booking_id: uuid.UUID,
    booking_update: BookingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Booking:
    """Update mutable fields (service_name, schedule, or status) of a booking.

    Ownership fields (customer_id, provider_id) cannot be modified.
    Status transitions are validated through strict role-based business rules.
    """
    return booking_service.update_booking(
        db=db,
        booking_id=booking_id,
        booking_update=booking_update,
        current_user=current_user,
    )


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a booking",
)
def cancel_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Booking:
    """Explicitly cancel a booking reservation.

    Valid from PENDING or CONFIRMED state.
    Cannot cancel COMPLETED or already CANCELLED bookings.
    """
    return booking_service.cancel_booking(
        db=db,
        booking_id=booking_id,
        current_user=current_user,
    )


@router.delete(
    "/{booking_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a booking (business-safe cancellation)",
)
def delete_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Execute business-safe deletion of a booking reservation.

    - PENDING bookings are safely transitioned to CANCELLED.
    - CONFIRMED, COMPLETED, or already CANCELLED bookings cannot be deleted.
    - Historical business records, reviews, and notifications are preserved.
    """
    booking_service.delete_booking(
        db=db,
        booking_id=booking_id,
        current_user=current_user,
    )
