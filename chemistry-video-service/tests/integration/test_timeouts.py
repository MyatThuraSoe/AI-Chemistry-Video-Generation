"""Timeout behavior through the public API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.generation import orchestrator as orchestrator_module
from app.main import create_app
from tests.conftest import build_settings, wait_for_job


class _AdvancingClock:
    """Advance six seconds per read so the second deadline check trips."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        current = self.now
        self.now += 6.0
        return current


def test_job_timeout_fails_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_settings(
        tmp_path,
        generation_mode="real",
        job_timeout_seconds=10,
    )
    container = Container(settings)
    monkeypatch.setattr(orchestrator_module, "time", _AdvancingClock())

    with TestClient(create_app(settings, container=container)) as client:
        response = client.post(
            "/v1/video-jobs",
            json={"query": "How does the pH scale work?"},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]

        finished = wait_for_job(client, job_id, timeout=30)

    assert finished["status"] == "failed", finished
    assert finished["stage"] == "concept_resolution"
    assert finished["artifact"] is None
    error = finished["error"]
    assert error["code"] == "JOB_TIMEOUT"
    assert error["stage"] == "concept_resolution"
    assert error["retryable"] is False
    assert error["details"] == {"timeout_seconds": 10}
    assert "Traceback" not in str(finished)
