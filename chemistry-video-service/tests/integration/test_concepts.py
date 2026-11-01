"""Concept catalog and service behaviour not covered by HTTP tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import wait_for_job

QUERIES = [
    ("How does the pH scale work?", "ph-scale"),
    ("Why do atoms form covalent bonds?", "covalent-bonding"),
    ("What is the difference between ionic and covalent bonding?", "ionic-vs-covalent"),
]


@pytest.mark.parametrize(("query", "concept_id"), QUERIES)
def test_all_required_queries_resolve_to_their_concept(
    client: TestClient,
    query: str,
    concept_id: str,
) -> None:
    response = client.post("/v1/video-jobs", json={"query": query})

    assert response.status_code == 202, response.text
    assert response.json()["concept_id"] == concept_id


def test_query_matching_is_case_and_whitespace_insensitive(client: TestClient) -> None:
    response = client.post("/v1/video-jobs", json={"query": "  HOW DOES THE PH SCALE WORK?  "})

    assert response.status_code == 202, response.text
    assert response.json()["query"] == "HOW DOES THE PH SCALE WORK?"
    assert response.json()["concept_id"] == "ph-scale"


def test_query_aliases_resolve(client: TestClient) -> None:
    response = client.post("/v1/video-jobs", json={"query": "explain the ph scale"})

    assert response.status_code == 202, response.text
    assert response.json()["concept_id"] == "ph-scale"


def test_idempotent_retry_returns_same_job_and_reuses_completed_artifact(
    client: TestClient,
) -> None:
    headers = {"Idempotency-Key": "stable-key"}
    first = client.post("/v1/video-jobs", json={"query": QUERIES[0][0]}, headers=headers)
    second = client.post("/v1/video-jobs", json={"query": QUERIES[0][0]}, headers=headers)

    assert first.status_code == second.status_code == 202
    job_id = first.json()["job_id"]
    assert second.json()["job_id"] == job_id

    finished = wait_for_job(client, job_id)
    assert finished["status"] == "completed", finished

    third = client.post("/v1/video-jobs", json={"query": QUERIES[0][0]}, headers=headers)
    assert third.json()["job_id"] == job_id
    assert third.json()["status"] == "completed"
