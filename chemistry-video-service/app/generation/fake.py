"""Fast, deterministic pipeline used by integration tests and local demos.

It exercises the same job state machine, repository updates and artifact
endpoints as the real pipeline, but produces a tiny synthetic MP4 with a sine
tone instead of rendering every scene. E2E tests use the real pipeline.
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from io import BytesIO
from typing import Any
from uuid import UUID

from PIL import Image, ImageDraw

from app.config import Settings
from app.domain.errors import PipelineError, RenderError
from app.domain.models import ArtifactInfo, JobError, VideoJob, iso_z
from app.domain.script import ConceptPack, Script
from app.domain.states import JobStage, JobStatus
from app.generation.audio_provider import NarrationProvider
from app.generation.concept_registry import ConceptRegistry
from app.generation.orchestrator import JobProgressReporter
from app.generation.providers.ffmpeg import FFmpegTools
from app.generation.storyboard_builder import Storyboard, build_storyboard
from app.observability.logging import log_event
from app.observability.metrics import MetricsRegistry
from app.storage.artifact_store import ArtifactStore
from app.storage.job_repository import JobRepository

logger = logging.getLogger(__name__)

FAKE_VIDEO_SECONDS = 12.0
FAKE_VIDEO_BITRATE = "160k"


class FakeGenerationPipeline:
    """Drop-in replacement for :class:`GenerationOrchestrator` in tests."""

    def __init__(
        self,
        settings: Settings,
        repository: JobRepository,
        store: ArtifactStore,
        registry: ConceptRegistry,
        tools: FFmpegTools,
        *,
        metrics: MetricsRegistry | None = None,
        narration_provider: NarrationProvider | None = None,
        step_delay_seconds: float = 0.02,
        fail_stage: JobStage | None = None,
        failure: PipelineError | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.store = store
        self.registry = registry
        self.tools = tools
        self.metrics = metrics or MetricsRegistry()
        self.narration_provider = narration_provider
        self.step_delay_seconds = max(0.0, step_delay_seconds)
        self.fail_stage = fail_stage
        self.failure = failure

    def run(self, job_id: UUID) -> VideoJob | None:
        job = self.repository.get(job_id)
        if job is None or job.is_terminal:
            return job
        if job.status == JobStatus.QUEUED:
            job = job.mark_started()
            job = self.repository.update(job.job_id, job.model_dump()) or job

        reporter = JobProgressReporter(self.repository, job, self.metrics)
        try:
            self._run(reporter)
        except PipelineError as exc:
            reporter.fail(
                JobError(
                    code=exc.code,
                    message=exc.message,
                    stage=reporter.current_stage,
                    retryable=exc.retryable,
                    attempt=reporter.job.attempts or None,
                    details=exc.details,
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep the worker alive
            reporter.fail(
                JobError(
                    code="INTERNAL_ERROR",
                    message="Fake pipeline failed unexpectedly.",
                    stage=reporter.current_stage,
                    retryable=True,
                    attempt=reporter.job.attempts or None,
                    details={"error": str(exc)[:300]},
                )
            )
        finally:
            self.store.remove_work_dir(job_id)
        return reporter.job

    # ------------------------------------------------------------------
    def _step(self, reporter: JobProgressReporter, stage: JobStage) -> None:
        self._maybe_fail(stage)
        reporter.enter(stage)
        if self.step_delay_seconds:
            time.sleep(self.step_delay_seconds)

    def _maybe_fail(self, stage: JobStage) -> None:
        if self.fail_stage == stage and self.failure is not None:
            raise self.failure

    def _run(self, reporter: JobProgressReporter) -> None:
        job = reporter.job

        self._step(reporter, JobStage.CONCEPT_RESOLUTION)
        pack = self.registry.resolve(job.query)
        reporter.set_concept(pack.concept_id)
        script = pack.script.model_copy(deep=True)

        self._step(reporter, JobStage.SCRIPT_SELECTION)
        self._step(reporter, JobStage.SCRIPT_VALIDATION)
        self.store.write_json(job.job_id, "script.json", script.model_dump(mode="json"))

        self._step(reporter, JobStage.STORYBOARD_GENERATION)
        storyboard = build_storyboard(script, pack, script_source="canonical")
        self.store.write_json(
            job.job_id,
            "storyboard.json",
            storyboard.model_dump(mode="json"),
        )

        self._step(reporter, JobStage.NARRATION_GENERATION)
        self._step(reporter, JobStage.SCENE_RENDERING)
        render = self._render_fake_video(job.job_id)

        self._step(reporter, JobStage.VIDEO_COMPOSITION)
        self._write_subtitles(job.job_id, script.title)
        self._write_thumbnail(job.job_id, script.title)

        self._step(reporter, JobStage.ARTIFACT_VALIDATION)
        completed_at = datetime.now().astimezone()
        metadata = self._metadata(
            reporter=reporter,
            pack=pack,
            script=script,
            storyboard=storyboard,
            render=render,
            completed_at=completed_at,
        )
        self.store.write_json(job.job_id, "metadata.json", metadata)
        self.store.write_json(
            job.job_id,
            "validation.json",
            {
                "valid": True,
                "renderer": "fake",
                "video": render,
                "checks": [{"name": "fake_pipeline", "passed": True, "detail": ""}],
            },
        )

        artifact = ArtifactInfo(
            job_id=job.job_id,
            video_url=f"/v1/video-jobs/{job.job_id}/artifact/video.mp4",
            metadata_url=f"/v1/video-jobs/{job.job_id}/artifact",
            subtitles_url=f"/v1/video-jobs/{job.job_id}/artifact/subtitles.vtt",
            thumbnail_url=f"/v1/video-jobs/{job.job_id}/artifact/thumbnail.jpg",
            duration_seconds=render["duration_seconds"],
            resolution=render["resolution"],
            format="mp4",
            checksum_sha256=render["checksum_sha256"],
        )
        reporter.complete(artifact, script_source="canonical")
        log_event(
            logger,
            "artifact_saved",
            job_id=str(job.job_id),
            concept_id=pack.concept_id,
            stage=reporter.current_stage,
        )

    # ------------------------------------------------------------------
    def _render_fake_video(self, job_id: UUID) -> dict[str, Any]:
        work_dir = self.store.work_dir(job_id)
        draft = work_dir / "fake.mp4"
        width = self.settings.video_width
        height = self.settings.video_height
        fps = self.settings.video_fps
        args = [
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x0B2B52:s={width}x{height}:r={fps}:d={FAKE_VIDEO_SECONDS}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=22050:duration={FAKE_VIDEO_SECONDS}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "stillimage",
            "-b:v",
            FAKE_VIDEO_BITRATE,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(draft),
        ]
        try:
            self.tools.run(args, timeout=120)
            if not draft.is_file() or draft.stat().st_size == 0:
                raise RenderError("Fake FFmpeg render produced no output.")
            destination = self.store.path_for(job_id, "video.mp4")
            shutil.copyfile(draft, destination)
            probe = self.tools.probe(destination)
        except PipelineError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize ffmpeg failures
            raise RenderError(f"Fake video generation failed: {exc}") from exc

        stream = probe.video_stream
        resolution = (
            f"{stream.width}x{stream.height}"
            if stream and stream.width and stream.height
            else f"{width}x{height}"
        )
        return {
            "path": "video.mp4",
            "duration_seconds": round(probe.duration_seconds, 3),
            "resolution": resolution,
            "fps": round(probe.fps or fps, 3),
            "codec": (stream.codec_name if stream else "h264") or "h264",
            "checksum_sha256": self.store.checksum_sha256(job_id, "video.mp4"),
        }

    def _write_subtitles(self, job_id: UUID, title: str) -> None:
        content = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:06.000\n"
            f"{title}\n\n"
            "00:00:06.000 --> 00:00:12.000\n"
            "A short chemistry lesson.\n"
        )
        self.store.write_text(job_id, "subtitles.vtt", content)

    def _write_thumbnail(self, job_id: UUID, title: str) -> None:
        image = Image.new("RGB", (320, 180), (5, 13, 31))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 312, 172), outline=(76, 201, 240), width=2)
        draw.text((20, 70), title[:36], fill=(248, 250, 252))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        self.store.write_bytes(job_id, "thumbnail.jpg", buffer.getvalue())

    def _metadata(
        self,
        *,
        reporter: JobProgressReporter,
        pack: ConceptPack,
        script: Script,
        storyboard: Storyboard,
        render: dict[str, Any],
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
            "script_source": "canonical",
            "script_version": pack.content_version,
            "audio_provider": "fake",
            "renderer": "fake",
            "video": render,
            "audio": {
                "provider": "fake",
                "is_placeholder": True,
                "voice": "sine",
            },
            "subtitles": {"path": "subtitles.vtt"},
            "thumbnail": {"path": "thumbnail.jpg"},
            "validation": {
                "script": "passed",
                "audio": "passed",
                "video": "passed",
            },
            "script": {
                "target_duration_seconds": script.target_duration_seconds,
                "scene_count": len(script.scenes),
            },
            "storyboard": {
                "scene_count": len(storyboard.scenes),
                "total_duration_seconds": storyboard.total_duration_seconds,
            },
        }


__all__ = ["FakeGenerationPipeline", "FAKE_VIDEO_SECONDS"]
