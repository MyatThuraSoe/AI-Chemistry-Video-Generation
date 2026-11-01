"""Artifact endpoint contract tests, including not-ready and failed jobs."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.domain.errors import RenderError
from app.generation.fake import FakeGenerationPipeline
from app.main import create_app
from tests.conftest import build_settings, wait_for_job

PH_QUERY = "How does the pH scale work?"


def _create(client: TestClient, query: str = PH_QUERY) -> dict:
    response = client.post("/v1/video-jobs", json={"query": query})
    assert response.status_code == 202, response.text
    return response.json()


def test_artifact_endpoint_returns_409_before_completion(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, fake_step_delay_seconds=0.5)
    with TestClient(create_app(settings)) as client:
        created = _create(client)

        response = client.get(f"/v1/video-jobs/{created['job_id']}/artifact")

        assert response.status_code == 409, response.text
        error = response.json()["error"]
        assert error["code"] == "ARTIFACT_NOT_READY"
        assert error["retryable"] is True
        assert error["status"] in {"queued", "running"}
        assert error["progress"] < 100

        finished = wait_for_job(client, created["job_id"], timeout=60)
        assert finished["status"] == "completed", finished


def test_completed_job_returns_artifact_metadata(client: TestClient) -> None:
    created = _create(client)
    finished = wait_for_job(client, created["job_id"])
    assert finished["status"] == "completed", finished

    response = client.get(f"/v1/video-jobs/{created['job_id']}/artifact")

    assert response.status_code == 200, response.text
    metadata = response.json()
    assert metadata["job_id"] == created["job_id"]
    assert metadata["concept_id"] == "ph-scale"
    assert metadata["query"] == PH_QUERY
    assert metadata["script_source"] == "canonical"
    assert metadata["validation"]["script"] == "passed"
    assert metadata["validation"]["audio"] == "passed"
    assert metadata["validation"]["video"] == "passed"
    assert metadata["video"]["path"] == "video.mp4"
    assert metadata["video"]["duration_seconds"] > 0
    assert metadata["video"]["resolution"] == "426x240"
    assert metadata["video"]["checksum_sha256"]
    assert metadata["subtitles"]["path"] == "subtitles.vtt"
    assert metadata["thumbnail"]["path"] == "thumbnail.jpg"
    assert metadata["audio"]["is_placeholder"] is True


def test_video_endpoint_returns_mp4_after_completion(client: TestClient) -> None:
    created = _create(client)
    finished = wait_for_job(client, created["job_id"])
    assert finished["status"] == "completed", finished

    response = client.get(f"/v1/video-jobs/{created['job_id']}/artifact/video.mp4")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("video/mp4")
    assert len(response.content) > 10_000
    assert b"ftyp" in response.content[:64]


def test_subtitles_and_thumbnail_after_completion(client: TestClient) -> None:
    created = _create(client)
    finished = wait_for_job(client, created["job_id"])
    assert finished["status"] == "completed", finished

    subtitles = client.get(f"/v1/video-jobs/{created['job_id']}/artifact/subtitles.vtt")
    assert subtitles.status_code == 200, subtitles.text
    assert subtitles.headers["content-type"].startswith("text/vtt")
    assert subtitles.text.startswith("WEBVTT")
    assert "-->" in subtitles.text

    thumbnail = client.get(f"/v1/video-jobs/{created['job_id']}/artifact/thumbnail.jpg")
    assert thumbnail.status_code == 200, thumbnail.text
    assert thumbnail.headers["content-type"].startswith("image/jpeg")
    assert thumbnail.content[:2] == b"\xff\xd8"


def test_failed_job_artifacts_return_409(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_settings(tmp_path)
    container = Container(settings)
    pipeline = FakeGenerationPipeline(
        settings,
        container.repository,
        container.store,
        container.registry,
        container.tools,
        metrics=container.metrics,
        narration_provider=container.narration_provider,
        step_delay_seconds=0.01,
    )

    def _boom(_job_id: UUID) -> dict:
        raise RenderError("Forced render failure for the failed-job test.")

    monkeypatch.setattr(pipeline, "_render_fake_video", _boom)
    container.pipeline = pipeline
    assert container.worker_pool is not None
    container.worker_pool.pipeline = pipeline

    with TestClient(create_app(settings, container=container)) as client:
        created = _create(client)
        finished = wait_for_job(client, created["job_id"])

        assert finished["status"] == "failed", finished
        assert finished["stage"] == "scene_rendering"
        assert finished["error"]["code"] == "RENDER_FAILED"
        assert finished["error"]["stage"] == "scene_rendering"
        assert finished["error"]["retryable"] is True
        assert finished["artifact"] is None

        for suffix in ("", "/video.mp4", "/subtitles.vtt", "/thumbnail.jpg"):
            response = client.get(f"/v1/video-jobs/{created['job_id']}/artifact{suffix}")
            assert response.status_code == 409, response.text
            error = response.json()["error"]
            assert error["code"] == "ARTIFACT_NOT_AVAILABLE"
            assert error["status"] == "failed"
            assert error["retryable"] is False


def test_artifact_endpoints_return_404_for_missing_job(client: TestClient) -> None:
    response = client.get(f"/v1/video-jobs/{UUID(int=0)}/artifact/video.mp4")

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"
