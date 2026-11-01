"""Thread-safe in-memory job repository for the local prototype."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.models import VideoJob, utc_now
from app.domain.states import JobStatus
from app.storage.job_repository import (
    JobFilters,
    JobPage,
    JobRepository,
    decode_cursor,
    encode_cursor,
)


class MemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self._jobs: dict[UUID, VideoJob] = {}
        self._lock = threading.RLock()

    def create(self, job: VideoJob) -> VideoJob:
        with self._lock:
            if job.job_id in self._jobs:
                raise ValueError(f"Job {job.job_id} already exists")
            self._jobs[job.job_id] = job.model_copy(deep=True)
            return job.model_copy(deep=True)

    def get(self, job_id: UUID) -> VideoJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def find_by_idempotency_key(self, key: str) -> VideoJob | None:
        with self._lock:
            matches = [job for job in self._jobs.values() if job.idempotency_key == key]
            if not matches:
                return None
            matches.sort(key=lambda job: job.created_at)
            return matches[0].model_copy(deep=True)

    def list(self, filters: JobFilters) -> JobPage:
        with self._lock:
            items = list(self._jobs.values())

        if filters.status is not None:
            items = [job for job in items if job.status == filters.status]
        if filters.concept_id is not None:
            items = [job for job in items if job.concept_id == filters.concept_id]

        items.sort(key=lambda job: (job.created_at, str(job.job_id)), reverse=True)

        if filters.cursor:
            cursor_time, cursor_id = decode_cursor(filters.cursor)
            items = [
                job for job in items if (job.created_at, str(job.job_id)) < (cursor_time, cursor_id)
            ]

        page = items[: filters.limit + 1]
        has_more = len(page) > filters.limit
        page = page[: filters.limit]
        next_cursor = encode_cursor(page[-1]) if has_more and page else None
        return JobPage(
            jobs=[job.model_copy(deep=True) for job in page],
            next_cursor=next_cursor,
        )

    def update(self, job_id: UUID, updates: dict[str, Any]) -> VideoJob | None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                return None
            payload = {**current.model_dump(), **updates}
            payload.setdefault("updated_at", utc_now())
            if "updated_at" not in updates:
                payload["updated_at"] = utc_now()
            updated = VideoJob.model_validate(payload)
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)

    def claim_next_queued(self) -> VideoJob | None:
        with self._lock:
            queued = [job for job in self._jobs.values() if job.status == JobStatus.QUEUED]
            if not queued:
                return None
            queued.sort(key=lambda job: (job.created_at, str(job.job_id)))
            started = queued[0].mark_started()
            self._jobs[started.job_id] = started
            return started.model_copy(deep=True)

    def count(self) -> int:
        with self._lock:
            return len(self._jobs)

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {status.value: 0 for status in JobStatus}
            for job in self._jobs.values():
                counts[job.status.value] += 1
            return counts

    def healthcheck(self) -> bool:
        return True

    def close(self) -> None:
        return None


class CursorHelper:
    """Small helper retained for tests that need deterministic cursor keys."""

    @staticmethod
    def key(job: VideoJob) -> tuple[datetime, str]:
        return job.created_at, str(job.job_id)
