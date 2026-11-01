"""Repository interface and pagination primitives."""

from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.errors import InvalidRequestError
from app.domain.models import VideoJob
from app.domain.states import JobStatus


class JobFilters(BaseModel):
    status: JobStatus | None = None
    concept_id: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None


class JobPage(BaseModel):
    jobs: list[VideoJob]
    next_cursor: str | None = None


def encode_cursor(job: VideoJob) -> str:
    raw = json.dumps(
        {"created_at": job.created_at.isoformat(), "job_id": str(job.job_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        payload = json.loads(raw)
        created_at = datetime.fromisoformat(payload["created_at"])
        job_id = str(UUID(payload["job_id"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidRequestError("The pagination cursor is invalid.") from exc
    return created_at, job_id


class JobRepository(ABC):
    """Persistence boundary for jobs.

    Implementations must be safe for use from the API event loop and blocking
    worker threads. The API never depends directly on a concrete repository.
    """

    @abstractmethod
    def create(self, job: VideoJob) -> VideoJob: ...

    @abstractmethod
    def get(self, job_id: UUID) -> VideoJob | None: ...

    @abstractmethod
    def find_by_idempotency_key(self, key: str) -> VideoJob | None: ...

    @abstractmethod
    def list(self, filters: JobFilters) -> JobPage: ...

    @abstractmethod
    def update(self, job_id: UUID, updates: dict[str, Any]) -> VideoJob | None: ...

    @abstractmethod
    def claim_next_queued(self) -> VideoJob | None:
        """Atomically claim the oldest queued job, marking it running."""

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def count_by_status(self) -> dict[str, int]: ...

    @abstractmethod
    def healthcheck(self) -> bool: ...

    @abstractmethod
    def close(self) -> None: ...
