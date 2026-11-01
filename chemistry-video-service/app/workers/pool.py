"""Bounded asynchronous worker pool for queued video jobs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Protocol
from uuid import UUID

from app.config import Settings
from app.domain.models import JobError
from app.domain.states import JobStatus
from app.observability.logging import log_event
from app.observability.metrics import MetricsRegistry
from app.storage.job_repository import JobRepository

logger = logging.getLogger(__name__)


class JobRunner(Protocol):
    def run(self, job_id: UUID) -> object: ...


class WorkerPool:
    """A fixed number of asyncio tasks, each running blocking jobs in a thread.

    Workers claim jobs directly from the repository rather than consuming an
    in-memory queue. A wake event avoids polling latency for fresh submissions,
    while the periodic poll keeps the pool usable from a separate process and
    recovers jobs left behind by a previous API instance.
    """

    def __init__(
        self,
        settings: Settings,
        repository: JobRepository,
        pipeline: JobRunner,
        metrics: MetricsRegistry,
        *,
        concurrency: int | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.pipeline = pipeline
        self.metrics = metrics
        self.concurrency = max(1, concurrency or settings.max_concurrent_jobs)
        self._tasks: list[asyncio.Task[None]] = []
        self._wake: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return bool(self._tasks) and not self._stopping

    async def start(self) -> None:
        if self._tasks:
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = False
        self._tasks = [
            asyncio.create_task(self._worker_loop(index), name=f"video-worker-{index}")
            for index in range(self.concurrency)
        ]
        log_event(
            logger,
            "worker_pool_started",
            workers=self.concurrency,
        )

    def notify(self, job_id: UUID | None = None) -> None:
        """Wake idle workers. Safe to call from the API event loop."""
        loop = self._loop
        wake = self._wake
        if loop is None or wake is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:
            return

    async def stop(self, timeout: float = 30.0) -> None:
        if not self._tasks:
            return
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        done, pending = await asyncio.wait(self._tasks, timeout=timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        log_event(
            logger,
            "worker_pool_stopped",
            workers=len(done) + len(pending),
        )

    # ------------------------------------------------------------------
    async def _worker_loop(self, index: int) -> None:
        assert self._wake is not None
        while not self._stopping:
            try:
                job = await asyncio.to_thread(self.repository.claim_next_queued)
            except Exception:
                logger.exception(
                    "Worker %s failed to claim a job",
                    index,
                    extra={"event": "worker_claim_failed"},
                )
                await asyncio.sleep(min(5.0, self.settings.worker_poll_interval_seconds))
                continue

            if job is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=self.settings.worker_poll_interval_seconds,
                    )
                self._wake.clear()
                continue

            self.metrics.inc("jobs_started")
            try:
                await asyncio.to_thread(self.pipeline.run, job.job_id)
            except Exception:
                logger.exception(
                    "Worker %s crashed while running job %s",
                    index,
                    job.job_id,
                    extra={
                        "event": "worker_job_crashed",
                        "job_id": str(job.job_id),
                    },
                )
                await self._mark_crashed(job.job_id)
            finally:
                self.notify()

    async def _mark_crashed(self, job_id: UUID) -> None:
        try:

            def _update() -> None:
                current = self.repository.get(job_id)
                if current is None or current.status in {
                    JobStatus.COMPLETED,
                    JobStatus.FAILED,
                    JobStatus.CANCELED,
                }:
                    return
                self.repository.update(
                    job_id,
                    current.mark_failed(
                        JobError(
                            code="INTERNAL_ERROR",
                            message="The generation worker crashed unexpectedly.",
                            stage=current.stage.value,
                            retryable=True,
                            attempt=current.attempts or None,
                        )
                    ).model_dump(),
                )

            await asyncio.to_thread(_update)
        except Exception:
            logger.exception(
                "Could not mark crashed job %s as failed",
                job_id,
                extra={"event": "worker_failure_update_failed", "job_id": str(job_id)},
            )


__all__ = ["JobRunner", "WorkerPool"]
