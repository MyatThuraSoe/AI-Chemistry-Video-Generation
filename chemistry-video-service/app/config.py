"""Application configuration loaded from environment variables via Pydantic Settings."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables (and the project `.env` file).
    Invalid values fail fast during application startup.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "chemistry-video-service"
    app_env: Literal["local", "test", "staging", "production"] = "local"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    api_key: str | None = None
    rate_limit_per_minute: int = Field(default=0, ge=0, le=100_000)
    max_request_bytes: int = Field(default=65_536, ge=1_024, le=10_485_760)

    artifact_dir: Path = Path("./artifacts")
    data_dir: Path = Path("./data")
    assets_dir: Path = Path("./assets")
    narration_cache_dir: Path | None = None

    job_repository: Literal["memory", "sqlite"] = "memory"
    database_url: str = "sqlite:///./data/app.db"

    video_width: int = Field(default=1280, ge=64, le=3840)
    video_height: int = Field(default=720, ge=64, le=2160)
    video_fps: int = Field(default=30, ge=1, le=60)
    video_quality: Literal["low", "medium", "high"] = "high"
    max_concurrent_jobs: int = Field(default=2, ge=1, le=32)
    job_timeout_seconds: int = Field(default=900, ge=10, le=7_200)

    script_source: Literal["canonical", "canonical_with_llm_fallback"] = "canonical"
    llm_provider: Literal["none", "mock", "openai_compatible"] = "none"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None

    tts_provider: Literal["canonical_cache", "espeak", "windows_sapi", "openai", "mock"] = (
        "canonical_cache"
    )
    tts_voice: str = ""
    tts_rate: int = Field(default=-1, ge=-10, le=10)
    tts_espeak_wpm: int = Field(default=150, ge=80, le=300)
    openai_api_key: str | None = None
    openai_tts_base_url: str = "https://api.openai.com/v1"
    openai_tts_model: str = "gpt-4o-mini-tts"
    allow_placeholder_audio: bool = False
    enable_idempotency: bool = True

    generation_mode: Literal["real", "fake"] = "real"
    fake_step_delay_seconds: float = Field(default=0.02, ge=0.0, le=5.0)
    worker_mode: Literal["embedded", "api_only", "standalone"] = "embedded"
    worker_poll_interval_seconds: float = Field(default=1.0, ge=0.05, le=60.0)
    keep_work_dir: bool = False
    callback_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    pipeline_version: str = "1.0.0"

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    ffmpeg_threads: int = Field(default=0, ge=0, le=64)
    ffmpeg_timeout_seconds: int = Field(default=300, ge=10, le=3_600)

    @field_validator("api_key", "llm_api_key", "openai_api_key", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        normalized = value.upper()
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return normalized

    @model_validator(mode="after")
    def _validate_and_resolve(self) -> Settings:
        if self.video_width % 2 != 0 or self.video_height % 2 != 0:
            raise ValueError("VIDEO_WIDTH and VIDEO_HEIGHT must be even for H.264 yuv420p output")

        if self.job_repository == "sqlite" and not self.database_url.startswith("sqlite:///"):
            raise ValueError(
                "Only sqlite:/// database URLs are supported by the built-in repository"
            )

        if self.generation_mode == "fake" and self.app_env == "production":
            raise ValueError("GENERATION_MODE=fake is not permitted in production")

        if self.tts_provider == "mock" and self.app_env == "production":
            raise ValueError("TTS_PROVIDER=mock is not permitted in production")

        self.artifact_dir = self._resolve_path(self.artifact_dir)
        self.data_dir = self._resolve_path(self.data_dir)
        self.assets_dir = self._resolve_path(self.assets_dir)
        if self.narration_cache_dir is None:
            self.narration_cache_dir = self.data_dir / "narration_cache"
        else:
            self.narration_cache_dir = self._resolve_path(self.narration_cache_dir)
        return self

    @staticmethod
    def _resolve_path(value: Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @property
    def sqlite_path(self) -> Path:
        """Return the filesystem path encoded in ``DATABASE_URL``."""
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("DATABASE_URL must use the sqlite:/// prefix")
        raw = self.database_url[len(prefix) :]
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def narration_assets_dir(self) -> Path:
        return self.assets_dir / "narration"

    def ensure_directories(self) -> None:
        """Create required directories and verify the artifact store is writable."""
        for directory in (
            self.artifact_dir,
            self.data_dir,
            self.assets_dir,
            self.narration_assets_dir,
            self.narration_cache_dir or (self.data_dir / "narration_cache"),
            self.work_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        if self.job_repository == "sqlite":
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        self.assert_writable(self.artifact_dir, "ARTIFACT_DIR")
        self.assert_writable(self.data_dir, "DATA_DIR")

    @staticmethod
    def assert_writable(directory: Path, label: str) -> None:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            fd, probe = tempfile.mkstemp(prefix=".write-probe-", dir=directory)
            os.close(fd)
            Path(probe).unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"{label} is not writable: {directory} ({exc})") from exc

    def public_dict(self) -> dict[str, Any]:
        """Configuration safe for logs and readiness responses (no secrets)."""
        return {
            "app_env": self.app_env,
            "job_repository": self.job_repository,
            "generation_mode": self.generation_mode,
            "worker_mode": self.worker_mode,
            "script_source": self.script_source,
            "tts_provider": self.tts_provider,
            "video": f"{self.video_width}x{self.video_height}@{self.video_fps}",
            "max_concurrent_jobs": self.max_concurrent_jobs,
        }

    def validate_runtime(self, *, require_media_tools: bool = True) -> dict[str, str]:
        """Validate runtime prerequisites and return a readiness check map.

        Raises ``RuntimeError`` when directories are unusable.
        """
        self.ensure_directories()
        checks: dict[str, str] = {"configuration": "ok", "artifact_store": "ok"}

        if require_media_tools:
            from app.generation.providers.ffmpeg import FFmpegTools

            tools = FFmpegTools(self)
            ffmpeg_ok, ffmpeg_detail = tools.check_ffmpeg()
            ffprobe_ok, ffprobe_detail = tools.check_ffprobe()
            checks["ffmpeg"] = "ok" if ffmpeg_ok else ffmpeg_detail
            checks["ffprobe"] = "ok" if ffprobe_ok else ffprobe_detail
        else:
            checks["ffmpeg"] = "skipped"
            checks["ffprobe"] = "skipped"
        return checks

    async def validate_repository(self, repository: Any) -> str:
        healthy = await _to_thread_call(repository.healthcheck)
        return "ok" if healthy else "unavailable"

    @staticmethod
    def parse_host(url: str) -> str | None:
        return urlparse(url).hostname


async def _to_thread_call(func: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(func)
