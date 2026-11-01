"""Dependency wiring shared by the FastAPI app and the standalone worker."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.api.rate_limit import RateLimiter
from app.config import Settings
from app.domain.script import ConceptPack
from app.generation.audio_provider import NarrationProvider, build_narration_provider
from app.generation.concept_registry import ConceptRegistry
from app.generation.content import load_concept_packs
from app.generation.fake import FakeGenerationPipeline
from app.generation.orchestrator import GenerationOrchestrator
from app.generation.providers.ffmpeg import FFmpegTools
from app.generation.providers.mock_llm_provider import build_script_provider
from app.generation.renderer import PillowFFmpegRenderer, SceneRenderer
from app.generation.video_validator import VideoValidator
from app.observability.logging import configure_logging, log_event
from app.observability.metrics import MetricsRegistry
from app.services.job_service import JobService
from app.storage.artifact_store import ArtifactStore, LocalArtifactStore
from app.storage.job_repository import JobRepository
from app.storage.memory_repository import MemoryJobRepository
from app.storage.sqlite_repository import SQLiteJobRepository
from app.workers.pool import WorkerPool

logger = logging.getLogger(__name__)


class Container:
    """Builds every long-lived dependency exactly once and owns their cleanup."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        configure_logging(self.settings)
        self.settings.ensure_directories()

        self.store: ArtifactStore = LocalArtifactStore(
            self.settings.artifact_dir,
            self.settings.work_dir,
        )
        self.repository: JobRepository = self._build_repository()
        self.packs: tuple[ConceptPack, ...] = load_concept_packs()
        self.registry = ConceptRegistry(self.packs)
        self.tools = FFmpegTools(self.settings)
        self.metrics = MetricsRegistry()
        self.rate_limiter = RateLimiter(self.settings.rate_limit_per_minute)
        self.narration_provider: NarrationProvider = build_narration_provider(
            self.settings, self.tools
        )

        self.renderer: SceneRenderer = PillowFFmpegRenderer(self.settings, self.tools)
        self.validator = VideoValidator(self.settings, self.tools)
        self.script_provider = build_script_provider(self.settings)

        if self.settings.generation_mode == "fake":
            self.pipeline: GenerationOrchestrator | FakeGenerationPipeline = FakeGenerationPipeline(
                self.settings,
                self.repository,
                self.store,
                self.registry,
                self.tools,
                metrics=self.metrics,
                narration_provider=self.narration_provider,
                step_delay_seconds=self.settings.fake_step_delay_seconds,
            )
        else:
            self.pipeline = GenerationOrchestrator(
                self.settings,
                self.repository,
                self.store,
                self.registry,
                self.tools,
                self.renderer,
                self.validator,
                self.narration_provider,
                self.script_provider,
                metrics=self.metrics,
            )

        self.worker_pool: WorkerPool | None = None
        if self.settings.worker_mode in {"embedded", "standalone"}:
            self.worker_pool = WorkerPool(
                self.settings,
                self.repository,
                self.pipeline,
                self.metrics,
            )

        self.job_service = JobService(
            self.settings,
            self.repository,
            self.store,
            self.registry,
            self.metrics,
            on_job_queued=self.worker_pool.notify if self.worker_pool else None,
        )

    # ------------------------------------------------------------------
    def _build_repository(self) -> JobRepository:
        if self.settings.job_repository == "sqlite":
            return SQLiteJobRepository(self.settings.sqlite_path)
        return MemoryJobRepository()

    async def start_workers(self) -> None:
        if self.worker_pool is not None:
            await self.worker_pool.start()

    async def stop_workers(self) -> None:
        if self.worker_pool is not None:
            await self.worker_pool.stop()

    async def shutdown(self) -> None:
        await self.stop_workers()
        self.narration_provider.close()
        self.repository.close()

    # ------------------------------------------------------------------
    def startup_checks(self) -> dict[str, str]:
        """Synchronous prerequisite checks used by startup and ``/readyz``."""
        checks: dict[str, str] = {"configuration": "ok", "artifact_store": "ok"}
        try:
            self.settings.ensure_directories()
        except (OSError, RuntimeError) as exc:
            checks["artifact_store"] = f"unavailable: {exc}"

        ffmpeg_ok, ffmpeg_detail = self.tools.check_ffmpeg()
        ffprobe_ok, ffprobe_detail = self.tools.check_ffprobe()
        checks["ffmpeg"] = "ok" if ffmpeg_ok else ffmpeg_detail
        checks["ffprobe"] = "ok" if ffprobe_ok else ffprobe_detail

        repository_ok = self.repository.healthcheck()
        checks["job_repository"] = "ok" if repository_ok else "unavailable"

        if self.settings.tts_provider == "canonical_cache":
            checks["narration_cache"] = (
                "ok"
                if self.settings.narration_cache_dir
                and Path(self.settings.narration_cache_dir).is_dir()
                else "unavailable"
            )
        return checks

    async def readiness(self) -> tuple[bool, dict[str, str]]:
        checks = await asyncio.to_thread(self.startup_checks)
        ready = all(value == "ok" for value in checks.values())
        return ready, checks

    def log_startup(self) -> None:
        checks = self.startup_checks()
        if all(value == "ok" for value in checks.values()):
            log_event(
                logger,
                "startup_checks_passed",
                **self.settings.public_dict(),
            )
            return
        log_event(
            logger,
            "startup_checks_failed",
            level=logging.WARNING,
            **{key: value for key, value in checks.items() if value != "ok"},  # type: ignore[arg-type]
        )


__all__ = ["Container"]
