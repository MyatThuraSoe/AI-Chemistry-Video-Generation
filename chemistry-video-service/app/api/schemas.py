"""Pydantic request/response models for the public HTTP API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.domain.models import ArtifactInfo, JobError
from app.domain.states import JobStage, JobStatus


class VideoJobCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(min_length=4, max_length=300)
    style: str | None = Field(default=None, max_length=64)
    callback_url: HttpUrl | None = None

    @field_validator("query")
    @classmethod
    def _query_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 4:
            raise ValueError("query must contain at least 4 non-whitespace characters")
        return stripped

    @field_validator("style")
    @classmethod
    def _style_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class JobLinks(BaseModel):
    self: str
    artifact: str
    video: str


class VideoJobCreateResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    stage: JobStage
    progress: int
    query: str
    concept_id: str | None
    created_at: str
    updated_at: str
    links: JobLinks


class VideoJobStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    stage: JobStage
    progress: int
    query: str
    concept_id: str | None
    created_at: str
    updated_at: str
    attempts: int
    error: JobError | None = None
    artifact: ArtifactInfo | None = None


class JobListItem(BaseModel):
    job_id: UUID
    status: JobStatus
    stage: JobStage
    progress: int
    query: str
    concept_id: str | None
    created_at: str
    updated_at: str
    has_artifact: bool


class JobListResponse(BaseModel):
    jobs: list[JobListItem]
    next_cursor: str | None = None


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
    version: str | None = None


class ConceptCatalogResponse(BaseModel):
    concepts: list[dict[str, Any]]


__all__ = [
    "ConceptCatalogResponse",
    "HealthResponse",
    "JobLinks",
    "JobListItem",
    "JobListResponse",
    "VideoJobCreateRequest",
    "VideoJobCreateResponse",
    "VideoJobStatusResponse",
]
