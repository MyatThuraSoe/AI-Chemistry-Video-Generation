"""End-to-end orchestration of one video job.

The orchestrator is deliberately synchronous: it runs inside a worker thread so
that blocking Pillow/FFmpeg work never stalls the API event loop. Every state
change is written through the repository so polling clients observe real
progress, and every failure is converted into a stable :class:`JobError`.
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from app.config import Settings
from app.domain.errors import (
    AudioValidationError,
    ConceptResolutionError,
    InternalPipelineError,
    JobTimeoutError,
    NarrationGenerationError,
    PipelineError,
    RenderError,
    ScriptValidationError,
    UnsupportedConceptError,
    VideoValidationError,
)
from app.domain.models import ArtifactInfo, JobError, VideoJob, iso_z, utc_now
from app.domain.script import ConceptPack, Script, ScriptValidationResult
from app.domain.states import STAGE_PROGRESS, JobStage, JobStatus
from app.generation.audio_provider import AudioResult, NarrationProvider
from app.generation.concept_registry import ConceptRegistry, normalize_query
from app.generation.providers.ffmpeg import FFmpegTools
from app.generation.providers.mock_llm_provider import ScriptGenerationProvider
from app.generation.renderer import RenderResult, SceneRenderer
from app.generation.script_validator import validate_script
from app.generation.storyboard_builder import Storyboard, build_storyboard
from app.generation.video_validator import VideoValidationReport, VideoValidator
from app.observability.logging import log_event
from app.observability.metrics import MetricsRegistry
from app.storage.artifact_store import ArtifactStore
from app.storage.job_repository import JobRepository

logger = logging.getLogger(__name__)

MAX_LLM_ATTEMPTS = 2
MAX_NARRATION_ATTEMPTS = 2
MAX_RENDER_ATTEMPTS = 2


class JobProgressReporter:
    """Serialize stage/progress updates for a single job.

    A reporter owns exactly one job and is only used from the worker thread that
    runs it, so the only shared state is the repository itself. Repository
    implementations are required to be thread-safe.
    """

    def __init__(
        self,
        repository: JobRepository,
        job: VideoJob,
        metrics: MetricsRegistry,
    ) -> None:
        self.repository = repository
        self.job = job
        self.metrics = metrics
        self.stage_durations: dict[str, float] = dict(job.stage_durations)
        self._stage_started_at = time.monotonic()

    @property
    def current_stage(self) -> str:
        return self.job.stage.value

    def _save(self, job: VideoJob) -> None:
        updated = self.repository.update(job.job_id, job.model_dump())
        if updated is not None:
            self.job = updated

    def _record_stage_duration(self) -> None:
        elapsed = time.monotonic() - self._stage_started_at
        if self.job.stage not in {
            JobStage.COMPLETED,
            JobStage.FAILED,
            JobStage.CANCELED,
        }:
            previous = self.stage_durations.get(self.job.stage.value, 0.0)
            self.stage_durations[self.job.stage.value] = round(previous + elapsed, 3)
            self.metrics.observe_stage(self.job.stage.value, elapsed)
        self._stage_started_at = time.monotonic()

    def enter(self, stage: JobStage) -> None:
        if self.job.is_terminal:
            raise PipelineError(
                "JOB_CANCELED",
                "The job is no longer running.",
                stage=self.current_stage,
                retryable=False,
            )
        if self.job.stage == stage:
            target = max(self.job.progress, STAGE_PROGRESS[stage])
            if target != self.job.progress:
                self._save(self.job.with_progress(target))
            return

        self._record_stage_duration()
        updated = self.job.moved_to(stage, STAGE_PROGRESS[stage])
        self._save(updated)
        log_event(
            logger,
            "job_stage_changed",
            job_id=str(self.job.job_id),
            concept_id=self.job.concept_id,
            stage=stage.value,
            progress=self.job.progress,
        )

    def progress(self, percent: int) -> None:
        bounded = max(self.job.progress, min(100, max(0, percent)))
        if bounded != self.job.progress:
            self._save(self.job.with_progress(bounded))

    def set_concept(self, concept_id: str) -> None:
        self.job = self.job.model_copy(
            update={
                "concept_id": concept_id,
                "normalized_query": normalize_query(self.job.query),
                "updated_at": utc_now(),
            }
        )
        self._save(self.job)

    def fail(self, error: JobError) -> VideoJob:
        if self.job.status == JobStatus.CANCELED:
            return self.job
        self._record_stage_duration()
        failed = self.job.mark_failed(error).model_copy(
            update={"stage_durations": dict(self.stage_durations)}
        )
        self._save(failed)
        self.metrics.inc("jobs_failed")
        log_event(
            logger,
            "job_failed",
            level=logging.ERROR,
            job_id=str(self.job.job_id),
            concept_id=self.job.concept_id,
            stage=self.job.stage.value,
            progress=self.job.progress,
            error_code=error.code,
        )
        return self.job

    def complete(self, artifact: ArtifactInfo, *, script_source: str) -> VideoJob:
        self._record_stage_duration()
        completed = self.job.moved_to(JobStage.COMPLETED, 100)
        completed = completed.model_copy(
            update={
                "artifact": artifact,
                "script_source": script_source,
                "stage_durations": dict(self.stage_durations),
                "completed_at": utc_now(),
            }
        )
        self._save(completed)
        self.metrics.inc("jobs_completed")
        log_event(
            logger,
            "job_completed",
            job_id=str(self.job.job_id),
            concept_id=self.job.concept_id,
            stage=self.job.stage.value,
            progress=self.job.progress,
            duration_ms=int(sum(self.stage_durations.values()) * 1000),
        )
        return self.job


class GenerationOrchestrator:
    """Run the full validation-first generation pipeline for a single job."""

    def __init__(
        self,
        settings: Settings,
        repository: JobRepository,
        store: ArtifactStore,
        registry: ConceptRegistry,
        tools: FFmpegTools,
        renderer: SceneRenderer,
        validator: VideoValidator,
        narration_provider: NarrationProvider,
        script_provider: ScriptGenerationProvider | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.store = store
        self.registry = registry
        self.tools = tools
        self.renderer = renderer
        self.validator = validator
        self.narration_provider = narration_provider
        self.script_provider = script_provider
        self.metrics = metrics or MetricsRegistry()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self, job_id: UUID) -> VideoJob | None:
        job = self.repository.get(job_id)
        if job is None:
            return None
        if job.is_terminal:
            return job
        if job.status == JobStatus.QUEUED:
            job = job.mark_started()
            updated = self.repository.update(job.job_id, job.model_dump())
            job = updated or job

        reporter = JobProgressReporter(self.repository, job, self.metrics)
        deadline = time.monotonic() + self.settings.job_timeout_seconds
        try:
            self._run_pipeline(reporter, deadline)
        except PipelineError as exc:
            error = JobError(
                code=exc.code,
                message=exc.message,
                stage=reporter.current_stage,
                retryable=exc.retryable,
                attempt=reporter.job.attempts or None,
                details=exc.details,
            )
            reporter.fail(error)
        except Exception:
            logger.exception(
                "Unhandled exception while generating video job %s",
                reporter.job.job_id,
                extra={
                    "event": "job_unhandled_error",
                    "job_id": str(reporter.job.job_id),
                    "stage": reporter.current_stage,
                },
            )
            reporter.fail(
                JobError(
                    code=InternalPipelineError().code,
                    message=("An unexpected internal error occurred during video generation."),
                    stage=reporter.current_stage,
                    retryable=True,
                    attempt=reporter.job.attempts or None,
                )
            )
        finally:
            if not self.settings.keep_work_dir:
                try:
                    self.store.remove_work_dir(job_id)
                except OSError:
                    logger.warning(
                        "Could not remove work directory for job %s",
                        job_id,
                        extra={"event": "work_dir_cleanup_failed", "job_id": str(job_id)},
                    )

        final_job = reporter.job
        self._send_callback(final_job)
        return final_job

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------
    def _run_pipeline(self, reporter: JobProgressReporter, deadline: float) -> None:
        job = reporter.job
        self._check_deadline(deadline, reporter)

        # 1. Concept resolution ------------------------------------------------
        reporter.enter(JobStage.CONCEPT_RESOLUTION)
        normalized = normalize_query(job.query)
        try:
            pack = self.registry.resolve_normalized(normalized)
        except UnsupportedConceptError as exc:
            raise ConceptResolutionError(
                "The query could not be matched to a supported concept.",
                details=exc.details,
            ) from exc
        reporter.set_concept(pack.concept_id)
        self._check_deadline(deadline, reporter)

        # 2. Script selection --------------------------------------------------
        reporter.enter(JobStage.SCRIPT_SELECTION)
        script, script_source, validation = self._select_script(pack, reporter)
        self._check_deadline(deadline, reporter)

        # 3. Script validation -------------------------------------------------
        reporter.enter(JobStage.SCRIPT_VALIDATION)
        if not validation.valid:
            raise ScriptValidationError(
                validation.errors[0],
                details={
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                },
            )
        self.store.write_json(
            job.job_id,
            "script.json",
            script.model_dump(mode="json"),
        )
        self._check_deadline(deadline, reporter)

        # 4. Storyboard generation (structural draft) -------------------------
        reporter.enter(JobStage.STORYBOARD_GENERATION)
        build_storyboard(script, pack, script_source=script_source)
        self._check_deadline(deadline, reporter)

        # 5. Narration generation ---------------------------------------------
        reporter.enter(JobStage.NARRATION_GENERATION)
        audio_durations, audio_paths, placeholders, audio_provider, placeholder = (
            self._generate_narration(script, reporter, deadline)
        )
        storyboard = build_storyboard(
            script,
            pack,
            audio_durations=audio_durations,
            audio_paths=audio_paths,
            placeholder_scene_ids=placeholders,
            script_source=script_source,
        )
        self.store.write_json(
            job.job_id,
            "storyboard.json",
            storyboard.model_dump(mode="json"),
        )
        self._check_deadline(deadline, reporter)

        # 6. Scene rendering (retry once while staying in this stage) ----------
        reporter.enter(JobStage.SCENE_RENDERING)
        render_result = self._render_with_retries(storyboard, reporter, deadline)

        # 7. Video composition ------------------------------------------------
        reporter.enter(JobStage.VIDEO_COMPOSITION)
        reporter.progress(STAGE_PROGRESS[JobStage.VIDEO_COMPOSITION])
        self._check_deadline(deadline, reporter, stage="video_composition")

        # 8. Artifact validation ----------------------------------------------
        reporter.enter(JobStage.ARTIFACT_VALIDATION)
        validation_report = self._validate_with_retry(
            reporter=reporter,
            storyboard=storyboard,
            render_result=render_result,
            script=script,
            pack=pack,
            script_source=script_source,
            audio_provider=audio_provider,
            placeholder=placeholder,
            deadline=deadline,
        )
        render_result = validation_report["render_result"]

        # 9. Final metadata + completion --------------------------------------
        completed_at = datetime.now().astimezone()
        metadata = self._build_metadata(
            reporter=reporter,
            pack=pack,
            script=script,
            storyboard=storyboard,
            render_result=render_result,
            script_source=script_source,
            audio_provider=audio_provider,
            placeholder=placeholder,
            validation_video="passed",
            completed_at=completed_at,
        )
        self.store.write_json(job.job_id, "metadata.json", metadata)
        self.store.write_json(
            job.job_id,
            "validation.json",
            validation_report["report"].model_dump(mode="json"),
        )
        log_event(
            logger,
            "artifact_validated",
            job_id=str(job.job_id),
            concept_id=pack.concept_id,
            stage=reporter.current_stage,
        )
        log_event(
            logger,
            "artifact_saved",
            job_id=str(job.job_id),
            concept_id=pack.concept_id,
            stage=reporter.current_stage,
        )

        artifact = ArtifactInfo(
            job_id=job.job_id,
            video_url=f"/v1/video-jobs/{job.job_id}/artifact/video.mp4",
            metadata_url=f"/v1/video-jobs/{job.job_id}/artifact",
            subtitles_url=f"/v1/video-jobs/{job.job_id}/artifact/subtitles.vtt",
            thumbnail_url=f"/v1/video-jobs/{job.job_id}/artifact/thumbnail.jpg",
            duration_seconds=render_result.duration_seconds,
            resolution=render_result.resolution,
            format="mp4",
            checksum_sha256=render_result.checksum_sha256,
        )
        reporter.complete(artifact, script_source=script_source)

    # ------------------------------------------------------------------
    # Script selection
    # ------------------------------------------------------------------
    def _select_script(
        self,
        pack: ConceptPack,
        reporter: JobProgressReporter,
    ) -> tuple[Script, str, ScriptValidationResult]:
        canonical = pack.script.model_copy(deep=True)
        if self.script_provider is None:
            return canonical, "canonical", validate_script(canonical, pack)

        previous_errors: list[str] = []
        for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
            try:
                candidate = self.script_provider.generate(pack, previous_errors)
            except PipelineError as exc:
                previous_errors = [exc.message]
                log_event(
                    logger,
                    "job_retry",
                    level=logging.WARNING,
                    job_id=str(reporter.job.job_id),
                    concept_id=pack.concept_id,
                    stage=reporter.current_stage,
                    attempt=attempt,
                    error_code=exc.code,
                )
                continue

            result = validate_script(candidate, pack)
            if result.valid:
                return candidate, "llm", result

            previous_errors = list(result.errors)
            log_event(
                logger,
                "job_retry",
                level=logging.WARNING,
                job_id=str(reporter.job.job_id),
                concept_id=pack.concept_id,
                stage=reporter.current_stage,
                attempt=attempt,
                error_code="SCRIPT_VALIDATION_FAILED",
            )

        logger.warning(
            "LLM script generation failed validation; falling back to canonical content",
            extra={
                "event": "script_fallback",
                "job_id": str(reporter.job.job_id),
                "concept_id": pack.concept_id,
            },
        )
        return canonical, "canonical", validate_script(canonical, pack)

    # ------------------------------------------------------------------
    # Narration
    # ------------------------------------------------------------------
    def _generate_narration(
        self,
        script: Script,
        reporter: JobProgressReporter,
        deadline: float,
    ) -> tuple[dict[int, float], dict[int, str], dict[int, bool], str, bool]:
        job_id = reporter.job.job_id
        work_dir = self.store.work_dir(job_id)
        narration_dir = work_dir / "narration"
        narration_dir.mkdir(parents=True, exist_ok=True)

        durations: dict[int, float] = {}
        paths: dict[int, str] = {}
        placeholders: dict[int, bool] = {}
        providers: set[str] = set()
        any_placeholder = False

        for index, scene in enumerate(script.scenes):
            self._check_deadline(deadline, reporter)
            result = self._synthesize_with_retries(
                scene.narration,
                reporter=reporter,
                scene_id=scene.scene_id,
            )
            destination = narration_dir / f"scene_{scene.scene_id:02d}.wav"
            if result.file_path.resolve() != destination.resolve():
                shutil.copyfile(result.file_path, destination)

            durations[scene.scene_id] = result.duration_seconds
            paths[scene.scene_id] = f"narration/{destination.name}"
            placeholders[scene.scene_id] = result.is_placeholder
            providers.add(result.provider)
            any_placeholder = any_placeholder or result.is_placeholder

            span = max(1, len(script.scenes))
            reporter.progress(
                STAGE_PROGRESS[JobStage.NARRATION_GENERATION] + int((index + 1) / span * 15)
            )

        provider_label = ",".join(sorted(providers)) or self.narration_provider.name
        return durations, paths, placeholders, provider_label, any_placeholder

    def _synthesize_with_retries(
        self,
        text: str,
        *,
        reporter: JobProgressReporter,
        scene_id: int,
    ) -> AudioResult:
        last_error: PipelineError | None = None
        for attempt in range(1, MAX_NARRATION_ATTEMPTS + 1):
            try:
                result = self.narration_provider.generate(text, self.settings.tts_voice or None)
                if result.is_placeholder and not self.settings.allow_placeholder_audio:
                    raise NarrationGenerationError(
                        "Placeholder narration is not allowed by configuration.",
                        retryable=False,
                    )
                return result
            except (NarrationGenerationError, AudioValidationError) as exc:
                last_error = exc
                log_event(
                    logger,
                    "job_retry",
                    level=logging.WARNING,
                    job_id=str(reporter.job.job_id),
                    stage=reporter.current_stage,
                    attempt=attempt,
                    error_code=exc.code,
                    scene_id=scene_id,
                )

        assert last_error is not None
        if isinstance(last_error, AudioValidationError):
            raise last_error
        raise NarrationGenerationError(
            f"Narration generation failed for scene {scene_id}: {last_error.message}",
            retryable=False,
            details=last_error.details,
        )

    # ------------------------------------------------------------------
    # Rendering and validation
    # ------------------------------------------------------------------
    def _render_with_retries(
        self,
        storyboard: Storyboard,
        reporter: JobProgressReporter,
        deadline: float,
    ) -> RenderResult:
        last_error: PipelineError | None = None
        for attempt in range(1, MAX_RENDER_ATTEMPTS + 1):
            try:
                return self.renderer.render(
                    storyboard,
                    job_id=reporter.job.job_id,
                    store=self.store,
                    deadline=deadline,
                    progress=lambda value: reporter.progress(
                        STAGE_PROGRESS[JobStage.SCENE_RENDERING]
                        + int(min(0.999, max(0.0, value)) * 15)
                    ),
                )
            except JobTimeoutError:
                raise
            except RenderError as exc:
                last_error = exc
            except Exception as exc:  # noqa: BLE001 - renderer boundary
                last_error = RenderError(f"Rendering failed: {exc}")
                logger.exception(
                    "Renderer raised an unexpected exception",
                    extra={
                        "event": "renderer_error",
                        "job_id": str(reporter.job.job_id),
                    },
                )

            if attempt < MAX_RENDER_ATTEMPTS:
                log_event(
                    logger,
                    "job_retry",
                    level=logging.WARNING,
                    job_id=str(reporter.job.job_id),
                    stage=reporter.current_stage,
                    attempt=attempt,
                    error_code=last_error.code,
                )

        assert last_error is not None
        raise last_error

    def _validate_with_retry(
        self,
        *,
        reporter: JobProgressReporter,
        storyboard: Storyboard,
        render_result: RenderResult,
        script: Script,
        pack: ConceptPack,
        script_source: str,
        audio_provider: str,
        placeholder: bool,
        deadline: float,
    ) -> dict[str, Any]:
        report = self._validate_once(
            reporter=reporter,
            storyboard=storyboard,
            render_result=render_result,
            script=script,
            pack=pack,
            script_source=script_source,
            audio_provider=audio_provider,
            placeholder=placeholder,
        )
        if report.valid:
            return {"render_result": render_result, "report": report}

        log_event(
            logger,
            "job_retry",
            level=logging.WARNING,
            job_id=str(reporter.job.job_id),
            stage=reporter.current_stage,
            attempt=1,
            error_code="VIDEO_VALIDATION_FAILED",
        )
        self._check_deadline(deadline, reporter)

        # Re-render once while remaining in artifact_validation. Re-entering
        # scene_rendering would be an invalid backwards state transition.
        try:
            render_result = self.renderer.render(
                storyboard,
                job_id=reporter.job.job_id,
                store=self.store,
                deadline=deadline,
            )
        except JobTimeoutError:
            raise
        except Exception as exc:  # noqa: BLE001 - renderer boundary
            raise RenderError(
                f"Rendering retry after validation failure failed: {exc}",
                stage="artifact_validation",
            ) from exc

        report = self._validate_once(
            reporter=reporter,
            storyboard=storyboard,
            render_result=render_result,
            script=script,
            pack=pack,
            script_source=script_source,
            audio_provider=audio_provider,
            placeholder=placeholder,
        )
        if not report.valid:
            self.store.write_json(
                reporter.job.job_id,
                "validation.json",
                report.model_dump(mode="json"),
            )
            raise VideoValidationError(
                f"Final video validation failed: {report.message}",
                details={
                    "errors": report.errors,
                    "checks": [check.model_dump() for check in report.checks],
                },
            )
        return {"render_result": render_result, "report": report}

    def _validate_once(
        self,
        *,
        reporter: JobProgressReporter,
        storyboard: Storyboard,
        render_result: RenderResult,
        script: Script,
        pack: ConceptPack,
        script_source: str,
        audio_provider: str,
        placeholder: bool,
    ) -> VideoValidationReport:
        completed_at = datetime.now().astimezone()
        metadata = self._build_metadata(
            reporter=reporter,
            pack=pack,
            script=script,
            storyboard=storyboard,
            render_result=render_result,
            script_source=script_source,
            audio_provider=audio_provider,
            placeholder=placeholder,
            validation_video="pending",
            completed_at=completed_at,
        )
        # The validator requires metadata.json to exist before it runs.
        self.store.write_json(reporter.job.job_id, "metadata.json", metadata)
        return self.validator.validate(
            job_id=reporter.job.job_id,
            store=self.store,
            expected_duration_seconds=storyboard.total_duration_seconds,
            metadata_payload=metadata,
            allow_placeholder_audio=self.settings.allow_placeholder_audio,
        )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------
    def _build_metadata(
        self,
        *,
        reporter: JobProgressReporter,
        pack: ConceptPack,
        script: Script,
        storyboard: Storyboard,
        render_result: RenderResult,
        script_source: str,
        audio_provider: str,
        placeholder: bool,
        validation_video: str,
        completed_at: datetime,
    ) -> dict[str, Any]:
        job = reporter.job
        return {
            "job_id": str(job.job_id),
            "concept_id": pack.concept_id,
            "title": script.title,
            "summary": script.summary,
            "query": job.query,
            "normalized_query": job.normalized_query,
            "created_at": iso_z(job.created_at),
            "completed_at": iso_z(completed_at),
            "pipeline_version": self.settings.pipeline_version,
            "script_source": script_source,
            "script_version": pack.content_version,
            "audio_provider": audio_provider,
            "renderer": render_result.renderer,
            "video": {
                "path": "video.mp4",
                "duration_seconds": render_result.duration_seconds,
                "resolution": render_result.resolution,
                "fps": render_result.fps,
                "codec": render_result.codec,
                "checksum_sha256": render_result.checksum_sha256,
            },
            "audio": {
                "provider": audio_provider,
                "is_placeholder": placeholder,
                "voice": self.settings.tts_voice or "default",
            },
            "subtitles": {"path": "subtitles.vtt"},
            "thumbnail": {"path": "thumbnail.jpg"},
            "validation": {
                "script": "passed",
                "audio": "passed",
                "video": validation_video,
            },
            "script": {
                "target_duration_seconds": script.target_duration_seconds,
                "scene_count": len(script.scenes),
            },
            "storyboard": {
                "scene_count": len(storyboard.scenes),
                "total_duration_seconds": storyboard.total_duration_seconds,
            },
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "layout": scene.layout,
                    "duration_seconds": scene.duration_seconds,
                    "narration_duration_seconds": scene.narration_duration_seconds,
                    "audio_path": scene.audio_path,
                    "is_placeholder_audio": scene.is_placeholder_audio,
                }
                for scene in storyboard.scenes
            ],
        }

    # ------------------------------------------------------------------
    # Timeouts and callbacks
    # ------------------------------------------------------------------
    def _check_deadline(
        self,
        deadline: float,
        reporter: JobProgressReporter,
        *,
        stage: str | None = None,
    ) -> None:
        if time.monotonic() > deadline:
            raise JobTimeoutError(
                self.settings.job_timeout_seconds,
                stage or reporter.current_stage,
            )

    def _send_callback(self, job: VideoJob) -> None:
        if not job.callback_url:
            return
        payload = job.model_dump(mode="json")
        try:
            with httpx.Client(timeout=self.settings.callback_timeout_seconds) as client:
                response = client.post(job.callback_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "Job callback delivery failed",
                extra={
                    "event": "callback_failed",
                    "job_id": str(job.job_id),
                    "error": str(exc),
                },
            )
        else:
            log_event(
                logger,
                "job_callback_delivered",
                job_id=str(job.job_id),
            )


__all__ = ["GenerationOrchestrator", "JobProgressReporter"]
