"""Final artifact validation using FFprobe and structural checks."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.config import Settings
from app.domain.errors import VideoValidationError
from app.generation.providers.ffmpeg import FFmpegTools, FFprobeError
from app.storage.artifact_store import ArtifactStore

MIN_VIDEO_BYTES = 10_000
MIN_THUMBNAIL_BYTES = 500


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class VideoValidationReport(BaseModel):
    valid: bool
    checks: list[ValidationCheck] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    width: int = 0
    height: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    file_size_bytes: int = 0
    checksum_sha256: str = ""
    expected_duration_seconds: float | None = None

    @property
    def message(self) -> str:
        return "; ".join(self.errors) if self.errors else "Artifact validation passed."


class VideoValidator:
    def __init__(self, settings: Settings, tools: FFmpegTools) -> None:
        self.settings = settings
        self.tools = tools

    def validate(
        self,
        *,
        job_id: UUID,
        store: ArtifactStore,
        expected_duration_seconds: float | None,
        metadata_payload: dict[str, Any] | None,
        allow_placeholder_audio: bool,
    ) -> VideoValidationReport:
        checks: list[ValidationCheck] = []
        errors: list[str] = []

        def check(
            name: str, passed: bool, failure_detail: str = "", success_detail: str = ""
        ) -> None:
            detail = success_detail if passed else failure_detail
            checks.append(ValidationCheck(name=name, passed=passed, detail=detail))
            if not passed:
                errors.append(f"{name}: {failure_detail}" if failure_detail else name)

        video_path = store.path_for(job_id, "video.mp4")
        subtitles_path = store.path_for(job_id, "subtitles.vtt")
        thumbnail_path = store.path_for(job_id, "thumbnail.jpg")
        metadata_path = store.path_for(job_id, "metadata.json")

        check(
            "video_exists",
            video_path.is_file(),
            "video.mp4 is missing",
            "video.mp4 exists",
        )
        size = video_path.stat().st_size if video_path.is_file() else 0
        check(
            "video_size",
            size >= MIN_VIDEO_BYTES,
            f"video is only {size} bytes",
            f"video is {size} bytes",
        )
        check(
            "subtitles_exist",
            subtitles_path.is_file(),
            "subtitles.vtt is missing",
            "subtitles.vtt exists",
        )
        check(
            "thumbnail_exists",
            thumbnail_path.is_file(),
            "thumbnail.jpg is missing",
            "thumbnail.jpg exists",
        )
        check(
            "metadata_exists",
            metadata_path.is_file(),
            "metadata.json is missing",
            "metadata.json exists",
        )

        probe = None
        if video_path.is_file():
            try:
                probe = self.tools.probe(video_path)
            except FFprobeError as exc:
                check("video_parseable", False, str(exc))
            else:
                check("video_parseable", True, "", "FFprobe parsed the MP4")

        video_stream = probe.video_stream if probe else None
        audio_stream = probe.audio_stream if probe else None
        check(
            "video_stream",
            video_stream is not None,
            "no video stream",
            "video stream present",
        )
        check(
            "audio_stream",
            audio_stream is not None,
            "no audio stream",
            "audio stream present",
        )

        duration = probe.duration_seconds if probe else 0.0
        check(
            "duration_positive",
            duration > 0.0,
            f"duration is {duration:.2f}s",
            f"duration is {duration:.2f}s",
        )
        if expected_duration_seconds is not None:
            tolerance = max(3.0, expected_duration_seconds * 0.08)
            within = abs(duration - expected_duration_seconds) <= tolerance
            check(
                "duration_expected",
                within,
                f"duration {duration:.2f}s differs from expected "
                f"{expected_duration_seconds:.2f}s by more than {tolerance:.2f}s",
                f"duration {duration:.2f}s is within {tolerance:.2f}s of expected "
                f"{expected_duration_seconds:.2f}s",
            )

        width = (video_stream.width or 0) if video_stream else 0
        height = (video_stream.height or 0) if video_stream else 0
        check(
            "resolution",
            width == self.settings.video_width and height == self.settings.video_height,
            f"expected {self.settings.video_width}x{self.settings.video_height}, "
            f"got {width}x{height}",
            f"resolution is {width}x{height}",
        )

        video_codec = (video_stream.codec_name or "") if video_stream else ""
        audio_codec = (audio_stream.codec_name or "") if audio_stream else ""
        check(
            "video_codec",
            video_codec in {"h264", "avc1"},
            f"unsupported video codec: {video_codec or 'none'}",
            f"video codec is {video_codec or 'none'}",
        )
        check(
            "audio_codec",
            audio_codec in {"aac", "mp4a"},
            f"unsupported audio codec: {audio_codec or 'none'}",
            f"audio codec is {audio_codec or 'none'}",
        )

        fps = probe.fps if probe else 0.0
        check(
            "frame_rate",
            abs(fps - self.settings.video_fps) <= 1.0,
            f"expected {self.settings.video_fps} fps, got {fps:.2f}",
            f"frame rate is {fps:.2f} fps",
        )

        if subtitles_path.is_file():
            subtitle_text = subtitles_path.read_text(encoding="utf-8", errors="replace")
            check(
                "subtitles_content",
                subtitle_text.startswith("WEBVTT") and "-->" in subtitle_text,
                "subtitles are not valid WebVTT cues",
                "subtitles contain WebVTT cues",
            )
        if thumbnail_path.is_file():
            thumb_size = thumbnail_path.stat().st_size
            check(
                "thumbnail_size",
                thumb_size >= MIN_THUMBNAIL_BYTES,
                "thumbnail is too small",
                f"thumbnail is {thumb_size} bytes",
            )
            try:
                with Image.open(thumbnail_path) as thumbnail:
                    check(
                        "thumbnail_valid",
                        thumbnail.format == "JPEG",
                        "thumbnail is not JPEG",
                        "thumbnail is JPEG",
                    )
            except (OSError, UnidentifiedImageError):
                check("thumbnail_valid", False, "thumbnail cannot be opened")

        placeholder = False
        metadata: dict[str, Any] | None = None
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                check("metadata_json", False, f"metadata.json is invalid: {exc}")
            else:
                check(
                    "metadata_json",
                    isinstance(metadata, dict),
                    "metadata must be an object",
                    "metadata.json parsed",
                )
                if isinstance(metadata, dict):
                    missing = _missing_metadata_fields(metadata)
                    check(
                        "metadata_fields",
                        not missing,
                        f"missing metadata fields: {', '.join(missing)}" if missing else "",
                        "all required metadata fields are present",
                    )
                    placeholder = bool(metadata.get("audio", {}).get("is_placeholder", False))
                    check(
                        "audio_placeholder_policy",
                        allow_placeholder_audio or not placeholder,
                        "placeholder audio is present but ALLOW_PLACEHOLDER_AUDIO=false",
                        "placeholder audio policy satisfied",
                    )
                    expected_checksum = str(metadata.get("video", {}).get("checksum_sha256", ""))
                    if expected_checksum and video_path.is_file():
                        check(
                            "checksum_matches",
                            expected_checksum == store.checksum_sha256(job_id, "video.mp4"),
                            "metadata checksum does not match video.mp4",
                            "metadata checksum matches video.mp4",
                        )

        if metadata_payload is not None and metadata is not None:
            check(
                "job_metadata_consistent",
                str(metadata.get("job_id")) == str(metadata_payload.get("job_id", "")),
                "metadata job_id does not match the job",
                "metadata job_id matches the job",
            )

        if not placeholder and video_path.is_file():
            mean_volume = self.tools.mean_volume_db(video_path)
            if mean_volume is not None:
                check(
                    "audio_not_silent",
                    mean_volume > -60.0,
                    f"final audio is silent (mean {mean_volume:.1f} dB)",
                    f"audio mean volume is {mean_volume:.1f} dB",
                )

        checksum = store.checksum_sha256(job_id, "video.mp4") if video_path.is_file() else ""
        return VideoValidationReport(
            valid=not errors,
            checks=checks,
            errors=errors,
            duration_seconds=round(duration, 3),
            width=width,
            height=height,
            video_codec=video_codec,
            audio_codec=audio_codec,
            file_size_bytes=size,
            checksum_sha256=checksum,
            expected_duration_seconds=expected_duration_seconds,
        )

    def require_valid(self, **kwargs: Any) -> VideoValidationReport:
        report = self.validate(**kwargs)
        if not report.valid:
            raise VideoValidationError(
                f"Final video validation failed: {report.message}",
                details={
                    "errors": report.errors,
                    "checks": [check.model_dump() for check in report.checks],
                },
            )
        return report


def _missing_metadata_fields(metadata: dict[str, Any]) -> list[str]:
    required_top = {
        "job_id",
        "concept_id",
        "title",
        "query",
        "created_at",
        "completed_at",
        "pipeline_version",
        "script_source",
        "script_version",
        "audio_provider",
        "renderer",
        "video",
        "audio",
        "subtitles",
        "thumbnail",
        "validation",
    }
    missing = [key for key in required_top if key not in metadata]
    video_fields = {"path", "duration_seconds", "resolution", "fps", "codec", "checksum_sha256"}
    if isinstance(metadata.get("video"), dict):
        missing.extend(f"video.{key}" for key in video_fields if key not in metadata["video"])
    validation_fields = {"script", "audio", "video"}
    if isinstance(metadata.get("validation"), dict):
        missing.extend(
            f"validation.{key}" for key in validation_fields if key not in metadata["validation"]
        )
    return missing
