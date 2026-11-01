"""End-to-end tests for the three required queries using the real pipeline.

These tests render at 426x240 / 5 fps with deterministic placeholder narration,
so they exercise script validation, storyboard generation, audio validation,
Pillow/FFmpeg rendering, composition and final artifact validation. They are
marked ``e2e`` because they are appreciably slower than the integration suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.generation.providers.ffmpeg import FFmpegTools
from app.main import create_app
from tests.conftest import build_settings, require_ffmpeg, wait_for_job

PH_QUERY = "How does the pH scale work?"
COVALENT_QUERY = "Why do atoms form covalent bonds?"
IONIC_QUERY = "What is the difference between ionic and covalent bonding?"

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def e2e_client(tmp_path_factory: pytest.TempPathFactory) -> Any:
    require_ffmpeg()
    root = tmp_path_factory.mktemp("e2e")
    settings = build_settings(
        root,
        generation_mode="real",
        script_source="canonical",
        tts_provider="mock",
        allow_placeholder_audio=True,
        job_timeout_seconds=900,
        worker_poll_interval_seconds=0.05,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def _run_required_query(
    client: TestClient,
    tmp_path: Path,
    *,
    query: str,
    concept_id: str,
) -> dict[str, Any]:
    created = client.post("/v1/video-jobs", json={"query": query})
    assert created.status_code == 202, created.text
    payload = created.json()
    assert payload["concept_id"] == concept_id
    job_id = payload["job_id"]
    tmp_path.mkdir(parents=True, exist_ok=True)

    finished = wait_for_job(client, job_id, timeout=600.0, poll_interval=0.2)
    assert finished["status"] == "completed", finished
    assert finished["stage"] == "completed"
    assert finished["progress"] == 100
    assert finished["error"] is None
    assert finished["artifact"] is not None

    metadata_response = client.get(f"/v1/video-jobs/{job_id}/artifact")
    assert metadata_response.status_code == 200, metadata_response.text
    metadata = metadata_response.json()
    assert metadata["job_id"] == job_id
    assert metadata["concept_id"] == concept_id
    assert metadata["script_source"] == "canonical"
    assert metadata["renderer"] != "fake"
    assert metadata["validation"] == {
        "script": "passed",
        "audio": "passed",
        "video": "passed",
    }
    assert metadata["audio"]["is_placeholder"] is True
    assert metadata["video"]["duration_seconds"] > 10.0
    assert metadata["video"]["resolution"] == "426x240"
    assert metadata["video"]["fps"] == pytest.approx(5.0, abs=0.5)
    assert metadata["storyboard"]["scene_count"] == len(metadata["scenes"])
    assert metadata["storyboard"]["total_duration_seconds"] > 10.0

    video_response = client.get(f"/v1/video-jobs/{job_id}/artifact/video.mp4")
    assert video_response.status_code == 200, video_response.text
    assert video_response.headers["content-type"].startswith("video/mp4")
    assert len(video_response.content) > 10_000
    assert b"ftyp" in video_response.content[:64]

    downloaded = tmp_path / f"{job_id}.mp4"
    downloaded.write_bytes(video_response.content)
    assert downloaded.stat().st_size == len(video_response.content)

    tools = FFmpegTools(Settings(app_env="test"))
    probe = tools.probe(downloaded)
    assert probe.video_stream is not None
    assert probe.audio_stream is not None
    assert probe.video_stream.codec_name in {"h264", "avc1"}
    assert probe.audio_stream.codec_name in {"aac", "mp4a"}
    assert probe.video_stream.width == 426
    assert probe.video_stream.height == 240
    assert probe.duration_seconds > 10.0
    assert abs(probe.duration_seconds - metadata["video"]["duration_seconds"]) < 1.0

    subtitles = client.get(f"/v1/video-jobs/{job_id}/artifact/subtitles.vtt")
    assert subtitles.status_code == 200, subtitles.text
    assert subtitles.headers["content-type"].startswith("text/vtt")
    assert subtitles.text.startswith("WEBVTT")
    assert "-->" in subtitles.text

    thumbnail = client.get(f"/v1/video-jobs/{job_id}/artifact/thumbnail.jpg")
    assert thumbnail.status_code == 200, thumbnail.text
    assert thumbnail.content[:2] == b"\xff\xd8"

    validation = _read_json(client, job_id, "validation.json")
    assert validation["valid"] is True
    assert validation["errors"] == []
    assert all(check["passed"] for check in validation["checks"])
    checks = {check["name"]: check for check in validation["checks"]}
    assert checks["video_exists"]["detail"] == "video.mp4 exists"
    assert checks["video_codec"]["detail"].startswith("video codec is ")
    assert checks["audio_codec"]["detail"].startswith("audio codec is ")
    assert "missing" not in checks["metadata_fields"]["detail"]
    if "audio_not_silent" in checks:
        assert "silent" not in checks["audio_not_silent"]["detail"]

    return metadata


def _read_json(client: TestClient, job_id: str, filename: str) -> dict[str, Any]:
    container = client.app.state.container
    return json.loads(container.store.read_text(UUID(job_id), filename))


def test_e2e_ph_scale_video_generation(e2e_client: TestClient, tmp_path: Path) -> None:
    metadata = _run_required_query(
        e2e_client,
        tmp_path,
        query=PH_QUERY,
        concept_id="ph-scale",
    )
    assert metadata["title"] == "How the pH Scale Works"


def test_e2e_covalent_bonding_video_generation(
    e2e_client: TestClient,
    tmp_path: Path,
) -> None:
    metadata = _run_required_query(
        e2e_client,
        tmp_path,
        query=COVALENT_QUERY,
        concept_id="covalent-bonding",
    )
    assert "covalent bond" in metadata["title"].lower()


def test_e2e_ionic_vs_covalent_video_generation(
    e2e_client: TestClient,
    tmp_path: Path,
) -> None:
    metadata = _run_required_query(
        e2e_client,
        tmp_path,
        query=IONIC_QUERY,
        concept_id="ionic-vs-covalent",
    )
    assert "ionic" in metadata["title"].lower()


@pytest.mark.reliability
def test_repeated_ph_scale_runs_succeed(e2e_client: TestClient, tmp_path: Path) -> None:
    runs: list[dict[str, Any]] = []
    for index in range(3):
        metadata = _run_required_query(
            e2e_client,
            tmp_path / f"run-{index + 1}",
            query=PH_QUERY,
            concept_id="ph-scale",
        )
        runs.append(metadata)

    assert len(runs) == 3
    assert {run["concept_id"] for run in runs} == {"ph-scale"}
    assert {run["script_source"] for run in runs} == {"canonical"}
    assert {run["script_version"] for run in runs} == {runs[0]["script_version"]}
    scene_counts = {run["storyboard"]["scene_count"] for run in runs}
    assert scene_counts == {runs[0]["storyboard"]["scene_count"]}
    for run in runs:
        assert run["validation"]["script"] == "passed"
        assert run["validation"]["audio"] == "passed"
        assert run["validation"]["video"] == "passed"

    # Canonical content and deterministic storyboard timing should keep the
    # rendered duration stable across runs.
    durations = [float(run["video"]["duration_seconds"]) for run in runs]
    assert max(durations) - min(durations) <= 0.5
