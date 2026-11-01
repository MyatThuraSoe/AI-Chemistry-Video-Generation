"""Public HTTP routes for health, jobs and artifacts."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.api.dependencies import (
    JobServiceDep,
    enforce_rate_limit,
    get_container,
    require_api_key,
)
from app.api.schemas import (
    ConceptCatalogResponse,
    JobLinks,
    JobListItem,
    JobListResponse,
    VideoJobCreateRequest,
    VideoJobCreateResponse,
    VideoJobStatusResponse,
)
from app.domain.models import VideoJob, iso_z
from app.domain.states import JobStatus
from app.storage.job_repository import JobFilters

public_router = APIRouter()
v1_router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)],
)


def _links(job_id: UUID) -> JobLinks:
    base = f"/v1/video-jobs/{job_id}"
    return JobLinks(
        self=base,
        artifact=f"{base}/artifact",
        video=f"{base}/artifact/video.mp4",
    )


def _create_response(job: VideoJob) -> VideoJobCreateResponse:
    return VideoJobCreateResponse(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        query=job.query,
        concept_id=job.concept_id,
        created_at=iso_z(job.created_at),
        updated_at=iso_z(job.updated_at),
        links=_links(job.job_id),
    )


def _status_response(job: VideoJob) -> VideoJobStatusResponse:
    return VideoJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        query=job.query,
        concept_id=job.concept_id,
        created_at=iso_z(job.created_at),
        updated_at=iso_z(job.updated_at),
        attempts=job.attempts,
        error=job.error,
        artifact=job.artifact,
    )


# ---------------------------------------------------------------------------
# Service endpoints
# ---------------------------------------------------------------------------
@public_router.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@public_router.get("/readyz", tags=["health"])
async def readyz(request: Request) -> JSONResponse:
    container = get_container(request)
    ready, checks = await container.readiness()
    payload = {"status": "ok" if ready else "not_ready", "checks": checks}
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@public_router.get("/metrics", tags=["health"])
async def metrics(request: Request) -> PlainTextResponse:
    container = get_container(request)
    counts = await asyncio.to_thread(container.repository.count_by_status)
    return PlainTextResponse(
        container.metrics.prometheus(job_counts=counts),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
@v1_router.post(
    "/video-jobs",
    response_model=VideoJobCreateResponse,
    status_code=202,
    tags=["video-jobs"],
)
async def create_video_job(
    payload: VideoJobCreateRequest,
    service: JobServiceDep,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=200),
    ] = None,
) -> VideoJobCreateResponse:
    job, _created = await asyncio.to_thread(
        service.create_job,
        query=payload.query,
        style=payload.style,
        callback_url=str(payload.callback_url) if payload.callback_url else None,
        idempotency_key=idempotency_key,
    )
    return _create_response(job)


@v1_router.get(
    "/video-jobs/{job_id}",
    response_model=VideoJobStatusResponse,
    tags=["video-jobs"],
)
async def get_video_job(
    service: JobServiceDep,
    job_id: Annotated[UUID, Path(description="Video job identifier")],
) -> VideoJobStatusResponse:
    job = await asyncio.to_thread(service.get_job, job_id)
    return _status_response(job)


@v1_router.get(
    "/video-jobs",
    response_model=JobListResponse,
    tags=["video-jobs"],
)
async def list_video_jobs(
    service: JobServiceDep,
    status: Annotated[JobStatus | None, Query()] = None,
    concept_id: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> JobListResponse:
    filters = JobFilters(
        status=status,
        concept_id=concept_id,
        limit=limit,
        cursor=cursor,
    )
    page = await asyncio.to_thread(service.list_jobs, filters)
    return JobListResponse(
        jobs=[
            JobListItem(
                job_id=job.job_id,
                status=job.status,
                stage=job.stage,
                progress=job.progress,
                query=job.query,
                concept_id=job.concept_id,
                created_at=iso_z(job.created_at),
                updated_at=iso_z(job.updated_at),
                has_artifact=job.artifact is not None,
            )
            for job in page.jobs
        ],
        next_cursor=page.next_cursor,
    )


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------
@v1_router.get("/video-jobs/{job_id}/artifact", tags=["artifacts"])
async def get_artifact_metadata(
    service: JobServiceDep,
    job_id: Annotated[UUID, Path(description="Video job identifier")],
) -> JSONResponse:
    metadata = await asyncio.to_thread(service.artifact_metadata, job_id)
    return JSONResponse(content=metadata)


@v1_router.get("/video-jobs/{job_id}/artifact/video.mp4", tags=["artifacts"])
async def get_artifact_video(
    service: JobServiceDep,
    job_id: Annotated[UUID, Path(description="Video job identifier")],
) -> FileResponse:
    _, path = await asyncio.to_thread(service.artifact_file, job_id, "video.mp4")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{job_id}.mp4",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@v1_router.get("/video-jobs/{job_id}/artifact/subtitles.vtt", tags=["artifacts"])
async def get_artifact_subtitles(
    service: JobServiceDep,
    job_id: Annotated[UUID, Path(description="Video job identifier")],
) -> FileResponse:
    _, path = await asyncio.to_thread(service.artifact_file, job_id, "subtitles.vtt")
    return FileResponse(
        path,
        media_type="text/vtt; charset=utf-8",
        filename=f"{job_id}.vtt",
    )


@v1_router.get("/video-jobs/{job_id}/artifact/thumbnail.jpg", tags=["artifacts"])
async def get_artifact_thumbnail(
    service: JobServiceDep,
    job_id: Annotated[UUID, Path(description="Video job identifier")],
) -> FileResponse:
    _, path = await asyncio.to_thread(service.artifact_file, job_id, "thumbnail.jpg")
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename=f"{job_id}.jpg",
    )


# ---------------------------------------------------------------------------
# Metadata extensions
# ---------------------------------------------------------------------------
@v1_router.get(
    "/concepts",
    response_model=ConceptCatalogResponse,
    tags=["metadata"],
)
async def list_concepts(service: JobServiceDep) -> ConceptCatalogResponse:
    return ConceptCatalogResponse(concepts=service.concept_catalog())


__all__ = ["public_router", "v1_router"]
