import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.review import Review
from app.models.user import User
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewUpdate
from app.services import review_service

router = APIRouter()


@router.post(
    "",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a review for a completed booking",
)
def create_review(
    review_in: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Review:
    """Create a new review for a completed booking.

    - Only customers can submit reviews.
    - The booking must belong to the authenticated customer.
    - The booking must be in COMPLETED status.
    - Only one review is permitted per booking.
    - customer_id and provider_id are derived securely and cannot be passed in
      the request.
    """
    return review_service.create_review(
        db=db,
        current_user=current_user,
        review_in=review_in,
    )


@router.get(
    "",
    response_model=list[ReviewResponse],
    status_code=status.HTTP_200_OK,
    summary="List reviews with role-based visibility",
)
def list_reviews(
    provider_id: uuid.UUID | None = Query(
        default=None, description="Filter reviews by provider ID"
    ),
    rating: int | None = Query(
        default=None, ge=1, le=5, description="Filter reviews by rating score"
    ),
    skip: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Review]:
    """List reviews according to caller role permissions.

    - **Customer**: Sees only reviews they authored.
    - **Provider**: Sees only reviews submitted for their services.
    - **Admin**: Sees all reviews across the platform.
    """
    return review_service.list_reviews(
        db=db,
        current_user=current_user,
        provider_id=provider_id,
        rating=rating,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{review_id}",
    response_model=ReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a review by ID",
)
def get_review(
    review_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Review:
    """Retrieve details of a single review.

    Access permitted to the author customer, assigned provider, or admin.
    """
    return review_service.get_review_by_id(
        db=db,
        review_id=review_id,
        current_user=current_user,
    )


@router.patch(
    "/{review_id}",
    response_model=ReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an existing review",
)
def update_review(
    review_id: uuid.UUID,
    review_update: ReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Review:
    """Update mutable fields (rating, comment) of an existing review.

    Only the original author customer may update their review.
    Ownership fields are strictly immutable.
    """
    return review_service.update_review(
        db=db,
        review_id=review_id,
        review_update=review_update,
        current_user=current_user,
    )


@router.delete(
    "/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a review",
)
def delete_review(
    review_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a review by ID.

    Permitted exclusively for the author customer or platform admin.
    Providers and unrelated customers receive 403 Forbidden.
    """
    review_service.delete_review(
        db=db,
        review_id=review_id,
        current_user=current_user,
    )
