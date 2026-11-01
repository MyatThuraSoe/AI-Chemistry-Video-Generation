"""Job state machine: high-level status, detailed stage, progress and transitions."""

from __future__ import annotations

from enum import StrEnum

from app.domain.errors import InvalidStateTransitionError


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class JobStage(StrEnum):
    QUEUED = "queued"
    CONCEPT_RESOLUTION = "concept_resolution"
    SCRIPT_SELECTION = "script_selection"
    SCRIPT_VALIDATION = "script_validation"
    STORYBOARD_GENERATION = "storyboard_generation"
    NARRATION_GENERATION = "narration_generation"
    SCENE_RENDERING = "scene_rendering"
    VIDEO_COMPOSITION = "video_composition"
    ARTIFACT_VALIDATION = "artifact_validation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


STAGE_PROGRESS: dict[JobStage, int] = {
    JobStage.QUEUED: 0,
    JobStage.CONCEPT_RESOLUTION: 5,
    JobStage.SCRIPT_SELECTION: 15,
    JobStage.SCRIPT_VALIDATION: 25,
    JobStage.STORYBOARD_GENERATION: 35,
    JobStage.NARRATION_GENERATION: 50,
    JobStage.SCENE_RENDERING: 70,
    JobStage.VIDEO_COMPOSITION: 85,
    JobStage.ARTIFACT_VALIDATION: 95,
    JobStage.COMPLETED: 100,
    JobStage.FAILED: 0,
    JobStage.CANCELED: 0,
}

STAGE_SEQUENCE: tuple[JobStage, ...] = (
    JobStage.QUEUED,
    JobStage.CONCEPT_RESOLUTION,
    JobStage.SCRIPT_SELECTION,
    JobStage.SCRIPT_VALIDATION,
    JobStage.STORYBOARD_GENERATION,
    JobStage.NARRATION_GENERATION,
    JobStage.SCENE_RENDERING,
    JobStage.VIDEO_COMPOSITION,
    JobStage.ARTIFACT_VALIDATION,
    JobStage.COMPLETED,
)

TERMINAL_STAGES: frozenset[JobStage] = frozenset(
    {JobStage.COMPLETED, JobStage.FAILED, JobStage.CANCELED}
)
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED}
)

# The happy-path order plus the permitted terminal transitions.
STAGE_TRANSITIONS: dict[JobStage, frozenset[JobStage]] = {
    JobStage.QUEUED: frozenset({JobStage.CONCEPT_RESOLUTION, JobStage.FAILED, JobStage.CANCELED}),
    JobStage.CONCEPT_RESOLUTION: frozenset({JobStage.SCRIPT_SELECTION, JobStage.FAILED}),
    JobStage.SCRIPT_SELECTION: frozenset({JobStage.SCRIPT_VALIDATION, JobStage.FAILED}),
    JobStage.SCRIPT_VALIDATION: frozenset({JobStage.STORYBOARD_GENERATION, JobStage.FAILED}),
    JobStage.STORYBOARD_GENERATION: frozenset({JobStage.NARRATION_GENERATION, JobStage.FAILED}),
    JobStage.NARRATION_GENERATION: frozenset({JobStage.SCENE_RENDERING, JobStage.FAILED}),
    JobStage.SCENE_RENDERING: frozenset({JobStage.VIDEO_COMPOSITION, JobStage.FAILED}),
    JobStage.VIDEO_COMPOSITION: frozenset({JobStage.ARTIFACT_VALIDATION, JobStage.FAILED}),
    JobStage.ARTIFACT_VALIDATION: frozenset({JobStage.COMPLETED, JobStage.FAILED}),
    JobStage.COMPLETED: frozenset(),
    JobStage.FAILED: frozenset(),
    JobStage.CANCELED: frozenset(),
}


def can_transition(current: JobStage, new: JobStage) -> bool:
    """Return whether a stage transition is valid.

    Re-reporting the current stage is allowed (progress-only updates use it).
    """
    if current == new:
        return True
    return new in STAGE_TRANSITIONS.get(current, frozenset())


def ensure_transition(current: JobStage, new: JobStage) -> None:
    if not can_transition(current, new):
        raise InvalidStateTransitionError(str(current), str(new))


def next_stage(current: JobStage) -> JobStage | None:
    """Return the next happy-path stage, or ``None`` for terminal stages."""
    try:
        index = STAGE_SEQUENCE.index(current)
    except ValueError:
        return None
    if index + 1 >= len(STAGE_SEQUENCE):
        return None
    return STAGE_SEQUENCE[index + 1]


def status_for_stage(stage: JobStage) -> JobStatus:
    if stage == JobStage.QUEUED:
        return JobStatus.QUEUED
    if stage == JobStage.COMPLETED:
        return JobStatus.COMPLETED
    if stage == JobStage.FAILED:
        return JobStatus.FAILED
    if stage == JobStage.CANCELED:
        return JobStatus.CANCELED
    return JobStatus.RUNNING


def is_terminal(stage: JobStage) -> bool:
    return stage in TERMINAL_STAGES


def progress_for_stage(stage: JobStage, *, fallback: int = 0) -> int:
    if stage in (JobStage.FAILED, JobStage.CANCELED):
        return fallback
    return STAGE_PROGRESS[stage]
