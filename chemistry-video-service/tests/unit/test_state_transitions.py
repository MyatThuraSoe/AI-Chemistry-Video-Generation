"""Job state-machine transitions and failure semantics."""

from __future__ import annotations

import pytest

from app.domain.errors import InvalidStateTransitionError
from app.domain.models import JobError, VideoJob
from app.domain.states import JobStage, JobStatus


def _job() -> VideoJob:
    return VideoJob(
        query="How does the pH scale work?",
        normalized_query="how does the ph scale work",
    )


def test_queued_can_move_to_concept_resolution() -> None:
    job = _job().moved_to(JobStage.CONCEPT_RESOLUTION)
    assert job.stage == JobStage.CONCEPT_RESOLUTION
    assert job.status == JobStatus.RUNNING
    assert job.progress == 5


def test_running_stage_can_move_to_failed() -> None:
    job = (
        _job()
        .moved_to(JobStage.CONCEPT_RESOLUTION)
        .moved_to(JobStage.SCRIPT_SELECTION)
        .moved_to(JobStage.SCRIPT_VALIDATION)
    )
    error = JobError(
        code="SCRIPT_VALIDATION_FAILED",
        message="Script is missing required term: hydrogen.",
        stage="script_validation",
        retryable=False,
    )
    failed = job.mark_failed(error)
    assert failed.status == JobStatus.FAILED
    assert failed.stage == JobStage.SCRIPT_VALIDATION
    assert failed.progress == 25
    assert failed.error is not None
    assert failed.error.code == "SCRIPT_VALIDATION_FAILED"
    assert failed.completed_at is not None


def test_completed_cannot_move_to_running() -> None:
    completed = _job().model_copy(
        update={
            "stage": JobStage.COMPLETED,
            "status": JobStatus.COMPLETED,
            "progress": 100,
        }
    )
    with pytest.raises(InvalidStateTransitionError):
        completed.moved_to(JobStage.SCENE_RENDERING)


def test_invalid_transition_raises_error() -> None:
    with pytest.raises(InvalidStateTransitionError) as captured:
        _job().moved_to(JobStage.SCENE_RENDERING)
    assert captured.value.code == "INVALID_STATE_TRANSITION"


def test_retry_increments_attempts_and_clears_error() -> None:
    job = _job().mark_started().mark_retry()
    assert job.attempts == 2
    assert job.error is None
