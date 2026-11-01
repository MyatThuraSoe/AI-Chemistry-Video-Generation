"""Domain models for video jobs and their artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.errors import PipelineError
from app.domain.states import (
    STAGE_PROGRESS,
    JobStage,
    JobStatus,
    ensure_transition,
    status_for_stage,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_z(value: datetime) -> str:
    """Serialize a datetime as an ISO-8601 UTC string with a trailing ``Z``."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class JobError(BaseModel):
    code: str
    message: str
    stage: str
    retryable: bool
    attempt: int | None = None
    details: dict[str, Any] | None = None


class ArtifactInfo(BaseModel):
    job_id: UUID
    video_url: str
    metadata_url: str
    subtitles_url: str
    thumbnail_url: str
    duration_seconds: float
    resolution: str
    format: str
    checksum_sha256: str


class VideoJob(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    job_id: UUID = Field(default_factory=uuid4)
    query: str
    normalized_query: str
    concept_id: str | None = None
    status: JobStatus = JobStatus.QUEUED
    stage: JobStage = JobStage.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    attempts: int = Field(default=0, ge=0)
    error: JobError | None = None
    artifact: ArtifactInfo | None = None
    idempotency_key: str | None = None
    callback_url: str | None = None
    style: str | None = None
    script_source: str | None = None
    stage_durations: dict[str, float] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED}

    def moved_to(self, stage: JobStage, progress: int | None = None) -> VideoJob:
        """Return a copy transitioned to ``stage``.

        ``completed`` is the only stage that implies a completed status. A failed
        job keeps the stage where it failed, matching the public API contract.
        """
        ensure_transition(self.stage, stage)
        now = utc_now()
        new_status = status_for_stage(stage)
        updates: dict[str, Any] = {
            "stage": stage,
            "status": new_status,
            "updated_at": now,
            "progress": (
                max(0, min(100, progress)) if progress is not None else STAGE_PROGRESS[stage]
            ),
        }
        if progress is None and new_status in {JobStatus.FAILED, JobStatus.CANCELED}:
            updates["progress"] = self.progress
        if self.started_at is None and stage != JobStage.QUEUED:
            updates["started_at"] = now
        if new_status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED}:
            updates["completed_at"] = now
        return self.model_copy(update=updates)

    def with_progress(self, progress: int) -> VideoJob:
        return self.model_copy(
            update={"progress": max(0, min(100, progress)), "updated_at": utc_now()}
        )

    def mark_failed(self, error: JobError) -> VideoJob:
        """Mark the job failed while preserving the stage where it failed."""
        return self.model_copy(
            update={
                "status": JobStatus.FAILED,
                "error": error,
                "progress": self.progress,
                "updated_at": utc_now(),
                "completed_at": utc_now(),
            }
        )

    def mark_started(self) -> VideoJob:
        if self.status != JobStatus.QUEUED:
            return self
        transitioned = self.moved_to(JobStage.CONCEPT_RESOLUTION)
        return transitioned.model_copy(update={"attempts": self.attempts + 1})

    def mark_retry(self) -> VideoJob:
        return self.model_copy(
            update={
                "attempts": self.attempts + 1,
                "error": None,
                "updated_at": utc_now(),
            }
        )

    def mark_canceled(self) -> VideoJob:
        return self.model_copy(
            update={
                "status": JobStatus.CANCELED,
                "updated_at": utc_now(),
                "completed_at": utc_now(),
            }
        )


class JobErrorFactory:
    """Build a domain ``JobError`` from a pipeline exception."""

    @staticmethod
    def from_pipeline(
        error: PipelineError,
        *,
        stage: str,
        attempt: int | None,
    ) -> JobError:
        return JobError(
            code=error.code,
            message=error.message,
            stage=error.stage or stage,
            retryable=error.retryable,
            attempt=attempt,
            details=error.details,
        )

    @staticmethod
    def internal(stage: str, message: str, attempt: int | None = None) -> JobError:
        return JobError(
            code="INTERNAL_ERROR",
            message=message,
            stage=stage,
            retryable=True,
            attempt=attempt,
        )


class JobSummary(BaseModel):
    """Compact job representation used by the list endpoint."""

    job_id: UUID
    status: JobStatus
    stage: JobStage
    progress: int
    query: str
    concept_id: str | None
    created_at: datetime
    updated_at: datetime
    has_artifact: bool
