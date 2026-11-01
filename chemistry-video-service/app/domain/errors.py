"""Stable error taxonomy and application exceptions.

Nothing in this module renders stack traces into API responses. The API layer
maps :class:`AppError` instances to a uniform JSON envelope.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorCode:
    """Stable, machine-readable error codes."""

    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_CONCEPT = "UNSUPPORTED_CONCEPT"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    ARTIFACT_NOT_READY = "ARTIFACT_NOT_READY"
    ARTIFACT_NOT_AVAILABLE = "ARTIFACT_NOT_AVAILABLE"
    CONCEPT_RESOLUTION_FAILED = "CONCEPT_RESOLUTION_FAILED"
    SCRIPT_VALIDATION_FAILED = "SCRIPT_VALIDATION_FAILED"
    SCRIPT_GENERATION_FAILED = "SCRIPT_GENERATION_FAILED"
    NARRATION_GENERATION_FAILED = "NARRATION_GENERATION_FAILED"
    AUDIO_VALIDATION_FAILED = "AUDIO_VALIDATION_FAILED"
    RENDER_FAILED = "RENDER_FAILED"
    VIDEO_VALIDATION_FAILED = "VIDEO_VALIDATION_FAILED"
    ARTIFACT_WRITE_FAILED = "ARTIFACT_WRITE_FAILED"
    JOB_TIMEOUT = "JOB_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # Extensions used by the production-hardening layer.
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    stage: str | None = None
    status: str | None = None
    progress: int | None = None
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Base exception surfaced to API clients with a stable error code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 500,
        retryable: bool = False,
        stage: str | None = None,
        details: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.stage = stage
        self.details = details
        self.extra = extra or {}

    def to_body(self) -> ErrorBody:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "stage": self.stage,
            "details": self.details,
        }
        payload.update(self.extra)
        return ErrorBody(**payload)


class InvalidRequestError(AppError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            ErrorCode.INVALID_REQUEST,
            message,
            http_status=400,
            details=details,
        )


class UnsupportedConceptError(AppError):
    def __init__(self, query: str) -> None:
        super().__init__(
            ErrorCode.UNSUPPORTED_CONCEPT,
            "The requested concept is not supported by this prototype.",
            http_status=422,
            details={
                "supported_concepts": [
                    "How does the pH scale work?",
                    "Why do atoms form covalent bonds?",
                    "What is the difference between ionic and covalent bonding?",
                ],
                "query": query,
            },
        )


class JobNotFoundError(AppError):
    def __init__(self, job_id: str) -> None:
        super().__init__(
            ErrorCode.JOB_NOT_FOUND,
            "The requested video job does not exist.",
            http_status=404,
            details={"job_id": job_id},
        )


class ArtifactNotReadyError(AppError):
    def __init__(self, status: str, stage: str, progress: int) -> None:
        super().__init__(
            ErrorCode.ARTIFACT_NOT_READY,
            "The video artifact is not ready yet.",
            http_status=409,
            retryable=True,
            stage=stage,
            extra={"status": status, "stage": stage, "progress": progress},
        )


class ArtifactNotAvailableError(AppError):
    def __init__(self, status: str, stage: str, progress: int, message: str | None = None) -> None:
        super().__init__(
            ErrorCode.ARTIFACT_NOT_AVAILABLE,
            message or "The job failed and no artifact is available.",
            http_status=409,
            retryable=False,
            stage=stage,
            extra={"status": status, "stage": stage, "progress": progress},
        )


class IdempotencyConflictError(AppError):
    def __init__(self) -> None:
        super().__init__(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            "This Idempotency-Key was already used for a different query.",
            http_status=409,
            details={"hint": "Use a new Idempotency-Key for a new query."},
        )


class UnauthorizedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            ErrorCode.UNAUTHORIZED,
            "A valid X-API-Key header is required.",
            http_status=401,
        )


class RateLimitedError(AppError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            ErrorCode.RATE_LIMITED,
            "Too many requests. Retry later.",
            http_status=429,
            retryable=True,
            details={"retry_after_seconds": retry_after_seconds},
        )


class RequestTooLargeError(AppError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            ErrorCode.REQUEST_TOO_LARGE,
            "The request body is larger than the configured limit.",
            http_status=413,
            details={"max_request_bytes": max_bytes},
        )


class InvalidStateTransitionError(AppError):
    def __init__(self, current_stage: str, new_stage: str) -> None:
        super().__init__(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Invalid job stage transition: {current_stage} -> {new_stage}.",
            http_status=500,
            stage=new_stage,
            details={"current_stage": current_stage, "new_stage": new_stage},
        )


class PipelineError(AppError):
    """Failure inside the generation pipeline; stored on the job, never raised to HTTP."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str | None = None,
        retryable: bool = False,
        attempt: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            http_status=500,
            retryable=retryable,
            stage=stage,
            details=details,
        )
        self.attempt = attempt


class ConceptResolutionError(PipelineError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            ErrorCode.CONCEPT_RESOLUTION_FAILED,
            message,
            stage="concept_resolution",
            retryable=False,
            details=details,
        )


class ScriptGenerationError(PipelineError):
    def __init__(
        self, message: str, *, retryable: bool = True, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(
            ErrorCode.SCRIPT_GENERATION_FAILED,
            message,
            stage="script_selection",
            retryable=retryable,
            details=details,
        )


class ScriptValidationError(PipelineError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            ErrorCode.SCRIPT_VALIDATION_FAILED,
            message,
            stage="script_validation",
            retryable=False,
            details=details,
        )


class NarrationGenerationError(PipelineError):
    def __init__(
        self, message: str, *, retryable: bool = True, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(
            ErrorCode.NARRATION_GENERATION_FAILED,
            message,
            stage="narration_generation",
            retryable=retryable,
            details=details,
        )


class AudioValidationError(PipelineError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            ErrorCode.AUDIO_VALIDATION_FAILED,
            message,
            stage="narration_generation",
            retryable=True,
            details=details,
        )


class RenderError(PipelineError):
    def __init__(
        self, message: str, *, stage: str = "scene_rendering", details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(
            ErrorCode.RENDER_FAILED,
            message,
            stage=stage,
            retryable=True,
            details=details,
        )


class VideoValidationError(PipelineError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            ErrorCode.VIDEO_VALIDATION_FAILED,
            message,
            stage="artifact_validation",
            retryable=True,
            details=details,
        )


class ArtifactWriteError(PipelineError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            ErrorCode.ARTIFACT_WRITE_FAILED,
            message,
            stage="artifact_validation",
            retryable=False,
            details=details,
        )


class JobTimeoutError(PipelineError):
    def __init__(self, timeout_seconds: int, stage: str) -> None:
        super().__init__(
            ErrorCode.JOB_TIMEOUT,
            f"Job exceeded the {timeout_seconds}s timeout.",
            stage=stage,
            retryable=False,
            details={"timeout_seconds": timeout_seconds},
        )


class InternalPipelineError(PipelineError):
    def __init__(
        self, message: str = "An unexpected internal error occurred during generation."
    ) -> None:
        super().__init__(
            ErrorCode.INTERNAL_ERROR,
            message,
            retryable=True,
        )


class ErrorEnvelope(BaseModel):
    """Generic wrapper used by tests and clients."""

    error: ErrorBody = Field(description="Stable error payload")
