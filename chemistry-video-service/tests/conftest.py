"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.generation.providers.ffmpeg import FFmpegTools
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"


def build_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "log_level": "WARNING",
        "log_format": "text",
        "generation_mode": "fake",
        "worker_mode": "embedded",
        "job_repository": "memory",
        "artifact_dir": tmp_path / "artifacts",
        "data_dir": tmp_path / "data",
        "assets_dir": ASSETS_DIR,
        "tts_provider": "mock",
        "allow_placeholder_audio": True,
        "video_width": 426,
        "video_height": 240,
        "video_fps": 5,
        "video_quality": "low",
        "max_concurrent_jobs": 2,
        "worker_poll_interval_seconds": 0.05,
        "fake_step_delay_seconds": 0.01,
        "job_timeout_seconds": 180,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return build_settings(tmp_path)


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def wait_for_job(
    client: TestClient,
    job_id: str,
    *,
    timeout: float = 120.0,
    poll_interval: float = 0.05,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/v1/video-jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in {"completed", "failed", "canceled"}:
            return last
        time.sleep(poll_interval)
    raise AssertionError(f"Job {job_id} did not finish in {timeout}s; last={last}")


def require_ffmpeg() -> None:
    tools = FFmpegTools(Settings(app_env="test"))
    ffmpeg_ok, ffmpeg_detail = tools.check_ffmpeg()
    ffprobe_ok, ffprobe_detail = tools.check_ffprobe()
    if not ffmpeg_ok or not ffprobe_ok:
        pytest.skip(f"FFmpeg/FFprobe unavailable: {ffmpeg_detail}; {ffprobe_detail}")
