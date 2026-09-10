import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.review import Review
from app.models.user import User
from app.schemas.review import (
    ProviderReviewSummary,
    ReviewCreate,
    ReviewUpdate,
)


def create_review(
    db: Session,
    current_user: User,
    review_in: ReviewCreate,
) -> Review:
    """Create review for a completed booking by the authenticated customer."""
    # 1. Only customers may create reviews
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers are permitted to submit reviews",
        )

    # 2. Find referenced booking
    booking = db.get(Booking, review_in.booking_id)
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    # 3. Verify authenticated user is the booking's customer
    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to review this booking",
        )

    # 4. Verify booking is completed (reject pending, confirmed, cancelled)
    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot review a booking with status '{booking.status.value}'. "
                f"Only completed bookings can be reviewed."
            ),
        )

    # 5. Prevent duplicate reviews (unique constraint on booking_id)
    existing_review = (
        db.execute(select(Review).where(Review.booking_id == review_in.booking_id))
        .scalars()
        .first()
    )
    if existing_review is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A review already exists for this booking",
        )

    # 6. Create and persist review
    review = Review(
        booking_id=booking.id,
        customer_id=current_user.id,
        provider_id=booking.provider_id,
        rating=review_in.rating,
        comment=review_in.comment,
    )

    try:
        db.add(review)
        db.commit()
        db.refresh(review)
        return review
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A review already exists for this booking",
        )


def get_review_by_id(
    db: Session,
    review_id: uuid.UUID,
    current_user: User,
) -> Review:
    """Retrieve a single review by ID with role-based access authorization."""
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    # Authorization check
    if current_user.role == UserRole.ADMIN:
        return review
    if current_user.role == UserRole.CUSTOMER and review.customer_id == current_user.id:
        return review
    if current_user.role == UserRole.PROVIDER and review.provider_id == current_user.id:
        return review

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access this review",
    )


def list_reviews(
    db: Session,
    current_user: User,
    provider_id: uuid.UUID | None = None,
    rating: int | None = None,
    skip: int = 0,
    limit: int = 20,
) -> list[Review]:
    """List reviews according to caller role visibility and optional filters."""
    stmt = select(Review)

    # Visibility constraints
    if current_user.role == UserRole.CUSTOMER:
        stmt = stmt.where(Review.customer_id == current_user.id)
    elif current_user.role == UserRole.PROVIDER:
        stmt = stmt.where(Review.provider_id == current_user.id)
    elif current_user.role == UserRole.ADMIN:
        pass  # Admin has platform-wide visibility

    # Filters
    if provider_id is not None:
        stmt = stmt.where(Review.provider_id == provider_id)
    if rating is not None:
        stmt = stmt.where(Review.rating == rating)

    stmt = stmt.order_by(Review.created_at.desc()).offset(skip).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_provider_review_summary(
    db: Session,
    provider_id: uuid.UUID,
) -> ProviderReviewSummary:
    """Compute provider review metrics using database SQL aggregation."""
    # 1. Verify provider exists and holds PROVIDER role
    provider = db.get(User, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )
    if provider.role != UserRole.PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected user is not registered as a service provider",
        )

    # 2. Count and average via SQL aggregation
    stats = db.execute(
        select(
            func.count(Review.id).label("total"),
            func.avg(Review.rating).label("avg_rating"),
        ).where(Review.provider_id == provider_id)
    ).first()

    total_count = stats.total if stats and stats.total is not None else 0
    avg_rating = (
        round(float(stats.avg_rating), 2)
        if stats and stats.avg_rating is not None
        else 0.0
    )

    # 3. Rating distribution (1 to 5) via GROUP BY
    dist_rows = db.execute(
        select(
            Review.rating,
            func.count(Review.id),
        )
        .where(Review.provider_id == provider_id)
        .group_by(Review.rating)
    ).all()

    distribution = {str(i): 0 for i in range(1, 6)}
    for r, cnt in dist_rows:
        distribution[str(r)] = cnt

    return ProviderReviewSummary(
        provider_id=provider_id,
        review_count=total_count,
        average_rating=avg_rating,
        rating_distribution=distribution,
    )


def update_review(
    db: Session,
    review_id: uuid.UUID,
    review_update: ReviewUpdate,
    current_user: User,
) -> Review:
    """Update mutable fields (rating, comment) of an existing review.

    Only the original author customer may update their review.
    """
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    # Only original customer author is permitted to update
    if current_user.role != UserRole.CUSTOMER or review.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author customer may update this review",
        )

    if review_update.rating is not None:
        review.rating = review_update.rating
    if review_update.comment is not None:
        review.comment = review_update.comment

    db.commit()
    db.refresh(review)
    return review


def delete_review(
    db: Session,
    review_id: uuid.UUID,
    current_user: User,
) -> None:
    """Delete a review by ID.

    Permitted exclusively for author customer or admin.
    """
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    is_author = (
        current_user.role == UserRole.CUSTOMER and review.customer_id == current_user.id
    )
    is_admin = current_user.role == UserRole.ADMIN

    if not (is_author or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this review",
        )

    db.delete(review)
    db.commit()
