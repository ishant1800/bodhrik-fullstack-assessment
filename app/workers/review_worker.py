"""Background worker consuming review summarisation tasks from Redis queue."""

import json
import logging
import signal
import sys
import uuid
from typing import Any

from app.core.redis import check_redis_connection, get_redis_client
from app.db.session import SessionLocal, check_db_connection
from app.services.review_summary_service import (
    QUEUE_NAME,
    process_summary_job,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bodhrik.worker")

# Flag for graceful shutdown
_running = True


def _handle_signal(signum: int, frame: Any) -> None:
    """Handle termination signals to permit graceful shutdown."""
    global _running
    logger.info("Termination signal %s received. Shutting down worker...", signum)
    _running = False


def run_worker(poll_timeout: int = 2, max_jobs: int | None = None) -> int:
    """Poll Redis queue and process review summarisation tasks.

    Args:
        poll_timeout: BLPOP block timeout in seconds.
        max_jobs: Optional maximum number of jobs to process before returning.

    Returns:
        Number of jobs successfully processed.
    """
    global _running
    _running = True

    # Register signal handlers if in main thread
    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    except (ValueError, AttributeError):
        pass  # Running in non-main thread during testing

    logger.info("Checking dependencies before starting worker loop...")
    if not check_redis_connection():
        logger.error("Cannot connect to Redis at startup. Worker exiting.")
        return 0
    if not check_db_connection():
        logger.error("Cannot connect to PostgreSQL at startup. Worker exiting.")
        return 0

    redis_client = get_redis_client()
    logger.info(
        "Review summarisation worker started. Listening on queue '%s'...",
        QUEUE_NAME,
    )

    jobs_processed = 0

    while _running:
        if max_jobs is not None and jobs_processed >= max_jobs:
            logger.info(
                "Reached maximum job processing limit (%d). Exiting loop.",
                max_jobs,
            )
            break

        try:
            # BLPOP removes the job item from the list (best-effort FIFO queue)
            item = redis_client.blpop(QUEUE_NAME, timeout=poll_timeout)
            if item is None:
                continue

            _, raw_payload = item
            task_data = json.loads(raw_payload)
            job_id = uuid.UUID(task_data["job_id"])
            provider_id = uuid.UUID(task_data["provider_id"])

            logger.info(
                "Processing summarisation job %s for provider %s",
                job_id,
                provider_id,
            )

            db = SessionLocal()
            try:
                process_summary_job(db=db, job_id=job_id, provider_id=provider_id)
                jobs_processed += 1
                logger.info("Completed summarisation job %s", job_id)
            finally:
                db.close()

        except (KeyboardInterrupt, SystemExit):
            logger.info("Interrupted. Exiting worker...")
            break
        except Exception as exc:
            logger.exception("Unexpected error in worker loop: %s", exc)

    logger.info("Worker stopped gracefully. Total jobs processed: %d", jobs_processed)
    return jobs_processed


if __name__ == "__main__":
    exit_code = 0 if run_worker() >= 0 else 1
    sys.exit(exit_code)
