"""In-process background job scheduler.

Single-process assumption:
This scheduler runs as an in-process asyncio background task within a single FastAPI
application worker process. It is designed for lightweight, single-process
deployments and does NOT provide distributed leader election or multi-process
synchronization. For horizontally scaled deployments, a distributed orchestrator
or dedicated worker process would be required.
"""

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.jobs.booking_jobs import run_booking_reminder_job, run_overdue_booking_job

logger = logging.getLogger(__name__)


class BackgroundJobScheduler:
    """Lightweight in-process asyncio scheduler for periodic background jobs."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running: bool = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the background scheduler task if not already running.

        Guards against duplicate scheduler tasks within the process.
        """
        if self.is_running:
            logger.warning(
                "Background job scheduler is already running; skipping start."
            )
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop found; background job scheduler not started."
            )
            return

        self._running = True
        self._task = loop.create_task(self._run_loop(), name="background_job_scheduler")
        logger.info("Background job scheduler started.")

    async def stop(self) -> None:
        """Stop the background scheduler cleanly and await task completion."""
        if not self._running and self._task is None:
            return

        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None
        logger.info("Background job scheduler stopped.")

    async def _run_loop(self) -> None:
        """Periodic loop executing registered background jobs."""
        interval_seconds = settings.BACKGROUND_JOB_INTERVAL_MINUTES * 60

        while self._running:
            try:
                self._execute_jobs()
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Unexpected error during scheduled background jobs: %s", exc
                )

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    def _execute_jobs(self) -> None:
        """Execute scheduled background jobs with dedicated database sessions."""
        # 1. Reminder job
        self._run_single_job("booking_reminder", run_booking_reminder_job)

        # 2. Overdue job
        self._run_single_job("booking_overdue", run_overdue_booking_job)

    def _run_single_job(self, job_name: str, job_fn: Callable[[Session], int]) -> None:
        """Run a single job function within a fresh SessionLocal() cleanly."""
        session = SessionLocal()
        try:
            processed = job_fn(session)
            logger.info(
                "Scheduled job '%s' completed successfully (processed: %d).",
                job_name,
                processed,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error executing scheduled job '%s': %s", job_name, exc)
        finally:
            session.close()


scheduler = BackgroundJobScheduler()
