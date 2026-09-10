import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.review import ProviderReviewSummary
from app.services import review_service

router = APIRouter()


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
