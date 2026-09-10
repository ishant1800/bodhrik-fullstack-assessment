import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.models.enums import UserRole
from app.models.review import Review
from app.models.user import User
from app.schemas.review_summary import (
    ReviewSummaryJobResponse,
    ReviewSummaryResult,
)

logger = logging.getLogger("bodhrik.review_summary")

QUEUE_NAME = "queue:review_summary"
JOB_KEY_PREFIX = "job:review_summary:"
JOB_TTL_SECONDS = 86400  # 24 hours


def enqueue_summary_job(
    db: Session,
    provider_id: uuid.UUID,
) -> ReviewSummaryJobResponse:
    """Validate provider and enqueue an asynchronous summarisation job in Redis."""
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

    job_id = uuid.uuid4()
    now = datetime.now(UTC)
    job_payload = {
        "job_id": str(job_id),
        "status": "queued",
        "provider_id": str(provider_id),
        "result": None,
        "error": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    try:
        redis_client = get_redis_client()
        # Save initial job state and push task message to the FIFO list
        redis_client.set(
            f"{JOB_KEY_PREFIX}{job_id}",
            json.dumps(job_payload),
            ex=JOB_TTL_SECONDS,
        )
        redis_client.rpush(
            QUEUE_NAME,
            json.dumps({"job_id": str(job_id), "provider_id": str(provider_id)}),
        )
    except Exception as exc:
        logger.error("Failed to enqueue review summary job in Redis: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue is temporarily unavailable",
        ) from exc

    return ReviewSummaryJobResponse.model_validate(job_payload)


def get_summary_job(job_id: uuid.UUID) -> ReviewSummaryJobResponse:
    """Retrieve the status and result of a review summarisation job from Redis."""
    try:
        redis_client = get_redis_client()
        raw_job = redis_client.get(f"{JOB_KEY_PREFIX}{job_id}")
    except Exception as exc:
        logger.error("Failed to retrieve review summary job from Redis: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue is temporarily unavailable",
        ) from exc

    if not raw_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Summary job not found",
        )

    data = json.loads(raw_job)
    return ReviewSummaryJobResponse.model_validate(data)


def process_summary_job(
    db: Session,
    job_id: uuid.UUID,
    provider_id: uuid.UUID,
) -> dict[str, Any]:
    """Execute review summarisation for a provider and update Redis job record."""
    redis_client = get_redis_client()
    job_key = f"{JOB_KEY_PREFIX}{job_id}"

    # Mark job as processing
    now = datetime.now(UTC)
    raw = redis_client.get(job_key)
    current_data = (
        json.loads(raw)
        if raw
        else {
            "job_id": str(job_id),
            "provider_id": str(provider_id),
            "created_at": now.isoformat(),
        }
    )
    current_data["status"] = "processing"
    current_data["updated_at"] = now.isoformat()
    redis_client.set(job_key, json.dumps(current_data), ex=JOB_TTL_SECONDS)

    try:
        provider = db.get(User, provider_id)
        if provider is None:
            current_data["status"] = "failed"
            current_data["error"] = "Provider not found"
            current_data["updated_at"] = datetime.now(UTC).isoformat()
            redis_client.set(job_key, json.dumps(current_data), ex=JOB_TTL_SECONDS)
            return current_data

        if provider.role != UserRole.PROVIDER:
            current_data["status"] = "failed"
            current_data["error"] = "User is not a provider"
            current_data["updated_at"] = datetime.now(UTC).isoformat()
            redis_client.set(job_key, json.dumps(current_data), ex=JOB_TTL_SECONDS)
            return current_data

        # Query reviews and aggregate statistics
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

        # Formulate deterministic natural language summary
        if total_count == 0:
            summary_text = (
                f"{provider.name} has no customer reviews yet. "
                "No ratings or qualitative feedback have been submitted."
            )
        elif avg_rating >= 4.5:
            summary_text = (
                f"{provider.name} has {total_count} reviews with an average "
                f"rating of {avg_rating:.2f}/5.0. Sentiment is overwhelmingly positive."
            )
        elif avg_rating >= 3.5:
            summary_text = (
                f"{provider.name} has {total_count} reviews with an average "
                f"rating of {avg_rating:.2f}/5.0. Sentiment is generally favorable."
            )
        elif avg_rating >= 2.5:
            summary_text = (
                f"{provider.name} has {total_count} reviews with an average "
                f"rating of {avg_rating:.2f}/5.0. Feedback is mixed."
            )
        else:
            summary_text = (
                f"{provider.name} has {total_count} reviews with an average "
                f"rating of {avg_rating:.2f}/5.0. Significant dissatisfaction noted."
            )

        finished_at = datetime.now(UTC)
        result_obj = ReviewSummaryResult(
            provider_id=provider_id,
            provider_name=provider.name,
            review_count=total_count,
            average_rating=avg_rating,
            rating_distribution=distribution,
            summary=summary_text,
            generated_at=finished_at,
        )

        current_data["status"] = "completed"
        current_data["result"] = result_obj.model_dump(mode="json")
        current_data["error"] = None
        current_data["updated_at"] = finished_at.isoformat()
        redis_client.set(job_key, json.dumps(current_data), ex=JOB_TTL_SECONDS)
        return current_data

    except Exception as exc:
        logger.exception("Error processing review summary job %s: %s", job_id, exc)
        current_data["status"] = "failed"
        current_data["error"] = str(exc)
        current_data["updated_at"] = datetime.now(UTC).isoformat()
        redis_client.set(job_key, json.dumps(current_data), ex=JOB_TTL_SECONDS)
        return current_data
