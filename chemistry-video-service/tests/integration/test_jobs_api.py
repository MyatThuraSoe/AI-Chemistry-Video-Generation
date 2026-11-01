"""API contract tests for job creation, polling and listing (fast pipeline)."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import wait_for_job

PH_QUERY = "How does the pH scale work?"
COVALENT_QUERY = "Why do atoms form covalent bonds?"


def _create(client: TestClient, query: str = PH_QUERY, **kwargs: object) -> dict:
    response = client.post("/v1/video-jobs", json={"query": query}, **kwargs)
    assert response.status_code == 202, response.text
    return response.json()


def test_create_job_returns_202(client: TestClient) -> None:
    response = client.post("/v1/video-jobs", json={"query": PH_QUERY})

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["stage"] == "queued"
    assert body["progress"] == 0
    assert body["query"] == PH_QUERY
    assert body["concept_id"] == "ph-scale"
    assert body["created_at"].endswith("Z")
    assert body["updated_at"].endswith("Z")
    assert body["links"]["self"] == f"/v1/video-jobs/{body['job_id']}"
    assert body["links"]["artifact"].endswith("/artifact")
    assert body["links"]["video"].endswith("/artifact/video.mp4")


def test_create_job_with_unknown_query_returns_422(client: TestClient) -> None:
    response = client.post("/v1/video-jobs", json={"query": "How do rockets reach orbit?"})

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_CONCEPT"
    assert error["retryable"] is False
    assert error["details"]["query"] == "How do rockets reach orbit?"
    assert PH_QUERY in error["details"]["supported_concepts"]


def test_get_job_returns_404_for_missing_job(client: TestClient) -> None:
    response = client.get(f"/v1/video-jobs/{uuid4()}")

    assert response.status_code == 404, response.text
    error = response.json()["error"]
    assert error["code"] == "JOB_NOT_FOUND"
    assert error["retryable"] is False
    assert "Traceback" not in response.text


def test_list_jobs_returns_created_job(client: TestClient) -> None:
    created = _create(client, COVALENT_QUERY)

    response = client.get("/v1/video-jobs")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_cursor"] is None
    listed = [job for job in body["jobs"] if job["job_id"] == created["job_id"]]
    assert len(listed) == 1
    assert listed[0]["query"] == COVALENT_QUERY
    assert listed[0]["concept_id"] == "covalent-bonding"
    assert listed[0]["has_artifact"] is False


def test_list_jobs_filters_by_concept_id(client: TestClient) -> None:
    _create(client, PH_QUERY)
    _create(client, COVALENT_QUERY)

    response = client.get("/v1/video-jobs", params={"concept_id": "covalent-bonding"})

    assert response.status_code == 200, response.text
    jobs = response.json()["jobs"]
    assert jobs
    assert all(job["concept_id"] == "covalent-bonding" for job in jobs)


def test_job_completes_and_can_be_polled(client: TestClient) -> None:
    created = _create(client)

    finished = wait_for_job(client, created["job_id"])

    assert finished["status"] == "completed", finished
    assert finished["stage"] == "completed"
    assert finished["progress"] == 100
    assert finished["attempts"] == 1
    assert finished["error"] is None
    assert finished["artifact"] is not None
    assert finished["artifact"]["format"] == "mp4"
    assert finished["artifact"]["duration_seconds"] > 0


def test_create_job_rejects_duplicate_idempotency_key_with_different_query(
    client: TestClient,
) -> None:
    first = _create(client, PH_QUERY, headers={"Idempotency-Key": "key-1"})
    second = _create(client, PH_QUERY, headers={"Idempotency-Key": "key-1"})
    assert second["job_id"] == first["job_id"]

    conflict = client.post(
        "/v1/video-jobs",
        json={"query": COVALENT_QUERY},
        headers={"Idempotency-Key": "key-1"},
    )

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert conflict.json()["error"]["retryable"] is False
