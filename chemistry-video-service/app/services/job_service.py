"""Application service that owns job creation and artifact access rules."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from app.config import Settings
from app.domain.errors import (
    ArtifactNotAvailableError,
    ArtifactNotReadyError,
    IdempotencyConflictError,
    JobNotFoundError,
)
from app.domain.models import VideoJob
from app.domain.states import JobStatus
from app.generation.concept_registry import ConceptRegistry, normalize_query
from app.observability.logging import log_event
from app.observability.metrics import MetricsRegistry
from app.storage.artifact_store import ArtifactStore
from app.storage.job_repository import JobFilters, JobPage, JobRepository

logger = logging.getLogger(__name__)


class JobService:
    """Coordinates repository, concept registry and worker notification."""

    def __init__(
        self,
        settings: Settings,
        repository: JobRepository,
        store: ArtifactStore,
        registry: ConceptRegistry,
        metrics: MetricsRegistry,
        *,
        on_job_queued: Callable[[UUID], None] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.store = store
        self.registry = registry
        self.metrics = metrics
        self.on_job_queued = on_job_queued
        # Serializes the idempotency check + insert so two concurrent requests
        # cannot create duplicate jobs for the same key.
        self._create_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def create_job(
        self,
        *,
        query: str,
        style: str | None = None,
        callback_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[VideoJob, bool]:
        """Create (or reuse) a job. Returns ``(job, created)``."""
        stripped = query.strip()
        pack = self.registry.resolve(stripped)
        normalized = normalize_query(stripped)

        key = idempotency_key.strip() if idempotency_key else None
        if key and not self.settings.enable_idempotency:
            key = None

        with self._create_lock:
            if key:
                existing = self.repository.find_by_idempotency_key(key)
                if existing is not None:
                    if existing.normalized_query != normalized:
                        raise IdempotencyConflictError()
                    return existing, False

            job = VideoJob(
                query=stripped,
                normalized_query=normalized,
                concept_id=pack.concept_id,
                style=style,
                callback_url=callback_url,
                idempotency_key=key,
            )
            created = self.repository.create(job)
            self.metrics.inc("jobs_created")
            log_event(
                logger,
                "job_created",
                job_id=str(created.job_id),
                concept_id=created.concept_id,
                query=created.query[:80],
            )
            log_event(
                logger,
                "job_queued",
                job_id=str(created.job_id),
                concept_id=created.concept_id,
                stage=created.stage.value,
                progress=created.progress,
            )

        if self.on_job_queued is not None:
            self.on_job_queued(created.job_id)
        return created, True

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_job(self, job_id: UUID) -> VideoJob:
        job = self.repository.get(job_id)
        if job is None:
            raise JobNotFoundError(str(job_id))
        return job

    def list_jobs(self, filters: JobFilters) -> JobPage:
        return self.repository.list(filters)

    def concept_catalog(self) -> list[dict[str, object]]:
        return [
            {
                "concept_id": pack.concept_id,
                "title": pack.script.title,
                "summary": pack.script.summary,
                "aliases": list(pack.aliases),
                "content_version": pack.content_version,
            }
            for pack in self.registry.packs
        ]

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------
    def artifact_metadata(self, job_id: UUID) -> dict[str, object]:
        job = self._require_completed_artifact(job_id)
        if not self.store.exists(job.job_id, "metadata.json"):
            raise ArtifactNotAvailableError(
                job.status.value,
                job.stage.value,
                job.progress,
                message="Artifact metadata is missing.",
            )
        import json

        return json.loads(self.store.read_text(job.job_id, "metadata.json"))

    def artifact_file(self, job_id: UUID, filename: str) -> tuple[VideoJob, Path]:
        job = self._require_completed_artifact(job_id)
        if not self.store.exists(job.job_id, filename):
            raise ArtifactNotAvailableError(
                job.status.value,
                job.stage.value,
                job.progress,
                message=f"Artifact file '{filename}' is missing.",
            )
        return job, self.store.path_for(job.job_id, filename)

    def _require_completed_artifact(self, job_id: UUID) -> VideoJob:
        job = self.get_job(job_id)
        if job.status == JobStatus.COMPLETED and job.artifact is not None:
            return job
        if job.status in {JobStatus.FAILED, JobStatus.CANCELED}:
            raise ArtifactNotAvailableError(
                job.status.value,
                job.stage.value,
                job.progress,
            )
        raise ArtifactNotReadyError(job.status.value, job.stage.value, job.progress)


__all__ = ["JobService"]
