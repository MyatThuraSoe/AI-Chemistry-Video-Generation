"""Production-hardening contract tests: validation, auth, limits and metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.observability.metrics import MetricsRegistry
from tests.conftest import build_settings

PH_QUERY = "How does the pH scale work?"


def test_invalid_json_body_returns_400(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/v1/video-jobs",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": "abc"},
        {"query": "   "},
        {"query": PH_QUERY, "unexpected": True},
        {"query": PH_QUERY, "callback_url": "not-a-url"},
    ],
)
def test_invalid_creation_payload_returns_400(tmp_path: Path, payload: dict) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/video-jobs", json=payload)

    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["retryable"] is False
    assert "Traceback" not in response.text


def test_api_key_is_enforced(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, api_key="secret-key")
    with TestClient(create_app(settings)) as client:
        missing = client.get("/v1/video-jobs")
        wrong = client.post(
            "/v1/video-jobs",
            json={"query": PH_QUERY},
            headers={"X-API-Key": "wrong"},
        )
        allowed = client.get("/v1/video-jobs", headers={"X-API-Key": "secret-key"})
        health = client.get("/healthz")

    assert missing.status_code == 401, missing.text
    assert missing.json()["error"]["code"] == "UNAUTHORIZED"
    assert wrong.status_code == 401, wrong.text
    assert wrong.json()["error"]["code"] == "UNAUTHORIZED"
    assert allowed.status_code == 200, allowed.text
    assert health.status_code == 200, health.text


def test_rate_limit_returns_429_with_retry_after(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, rate_limit_per_minute=2)
    with TestClient(create_app(settings)) as client:
        headers = {}
        first = client.get("/v1/video-jobs", headers=headers)
        second = client.get("/v1/video-jobs", headers=headers)
        third = client.get("/v1/video-jobs", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429, third.text
    assert third.json()["error"]["code"] == "RATE_LIMITED"
    assert int(third.headers["Retry-After"]) >= 1


def test_oversized_request_returns_413(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, max_request_bytes=1024)
    body = json.dumps({"query": PH_QUERY, "padding": "x" * 4096}).encode()
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/v1/video-jobs",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413, response.text
    error = response.json()["error"]
    assert error["code"] == "REQUEST_TOO_LARGE"
    assert error["details"]["max_request_bytes"] == 1024


def test_request_id_header_is_propagated(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        generated = client.get("/healthz")
        explicit = client.get("/healthz", headers={"X-Request-ID": "request-123"})

    assert generated.headers["X-Request-ID"]
    assert explicit.headers["X-Request-ID"] == "request-123"


def test_health_readiness_metrics_and_concepts(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        concepts = client.get("/v1/concepts")
        client.post("/v1/video-jobs", json={"query": PH_QUERY})
        metrics = client.get("/metrics")

    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ok"
    assert set(ready.json()["checks"]) >= {"configuration", "artifact_store", "job_repository"}

    assert concepts.status_code == 200, concepts.text
    concept_ids = {item["concept_id"] for item in concepts.json()["concepts"]}
    assert concept_ids == {"ph-scale", "covalent-bonding", "ionic-vs-covalent"}

    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers["content-type"]
    assert "chemistry_jobs_active" in metrics.text
    assert "chemistry_jobs_created" in metrics.text


def test_metrics_registry_snapshot_and_prometheus_output() -> None:
    metrics = MetricsRegistry()
    metrics.inc("jobs_created")
    metrics.inc("jobs_created", 2)
    metrics.observe_stage("script_validation", 0.25)

    assert metrics.snapshot() == {"jobs_created": 3}
    rendered = metrics.prometheus(job_counts={"queued": 1, "completed": 2})

    assert 'chemistry_jobs_active{status="completed"} 2' in rendered
    assert "chemistry_jobs_created 3" in rendered
    assert 'chemistry_job_stage_duration_seconds_count{stage="script_validation"} 1' in rendered
