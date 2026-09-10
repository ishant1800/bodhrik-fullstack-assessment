import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.provider import ProviderAvailabilityResponse, ProviderResponse
from app.schemas.review import ProviderReviewSummary
from app.services import provider_service, review_service

router = APIRouter()


@router.get(
    "",
    response_model=list[ProviderResponse],
    status_code=status.HTTP_200_OK,
    summary="List available service providers",
)
def list_providers(
    search: str | None = Query(
        default=None,
        max_length=100,
        description="Search providers by name or email",
    ),
    skip: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[User]:
    """Retrieve a paginated list of registered service providers."""
    return provider_service.list_providers(
        db=db,
        search=search,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{provider_id}/availability",
    response_model=ProviderAvailabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Check provider availability for a requested time slot",
)
def check_provider_availability(
    provider_id: uuid.UUID,
    start_time: datetime = Query(
        ...,
        description="Requested start timestamp (ISO 8601, timezone-aware)",
    ),
    end_time: datetime = Query(
        ...,
        description="Requested end timestamp (ISO 8601, timezone-aware)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProviderAvailabilityResponse:
    """Check whether a service provider is free from conflicting bookings."""
    if start_time.tzinfo is None or start_time.tzinfo.utcoffset(start_time) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_time must be timezone-aware",
        )
    if end_time.tzinfo is None or end_time.tzinfo.utcoffset(end_time) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_time must be timezone-aware",
        )
    if end_time <= start_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_time must be after start_time",
        )

    return provider_service.check_provider_availability(
        db=db,
        provider_id=provider_id,
        start_time=start_time,
        end_time=end_time,
    )


@router.get(
    "/{provider_id}/reviews/summary",
    response_model=ProviderReviewSummary,
    status_code=status.HTTP_200_OK,
    summary="Get aggregated review metrics for a service provider",
)
def get_provider_review_summary(
    provider_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProviderReviewSummary:
    """Retrieve aggregate review statistics for a service provider.

    Calculates total review count, average rating, and rating score distribution
    using database SQL aggregation.
    """
    return review_service.get_provider_review_summary(
        db=db,
        provider_id=provider_id,
    )


@router.get(
    "/{provider_id}",
    response_model=ProviderResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve service provider profile by ID",
)
def get_provider(
    provider_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Retrieve public profile information for a service provider."""
    return provider_service.get_provider_by_id(
        db=db,
        provider_id=provider_id,
    )
