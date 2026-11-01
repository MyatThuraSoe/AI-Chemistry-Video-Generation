"""FFmpeg encoding primitives used by the deterministic renderer."""

from __future__ import annotations

import math
import os
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

from app.config import Settings
from app.domain.errors import JobTimeoutError, RenderError
from app.generation.providers.ffmpeg import FFmpegTools, _no_window_flags

QUALITY_SETTINGS: dict[str, tuple[str, int, str]] = {
    "high": ("medium", 20, "160k"),
    "medium": ("veryfast", 24, "128k"),
    "low": ("ultrafast", 30, "96k"),
}


class FFmpegSceneEncoder:
    def __init__(self, settings: Settings, tools: FFmpegTools) -> None:
        self.settings = settings
        self.tools = tools
        preset, crf, audio_bitrate = QUALITY_SETTINGS[settings.video_quality]
        self.preset = preset
        self.crf = crf
        self.audio_bitrate = audio_bitrate

    def frame_count(self, duration_seconds: float) -> int:
        return max(1, math.ceil(duration_seconds * self.settings.video_fps))

    def encode_scene(
        self,
        frames: Iterable[bytes],
        audio_path: Path,
        output_path: Path,
        *,
        duration_seconds: float,
        deadline: float,
    ) -> Path:
        if not Path(audio_path).is_file():
            raise RenderError(f"Scene audio is missing: {audio_path.name}")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise JobTimeoutError(self.settings.job_timeout_seconds, "scene_rendering")

        audio_filter = (
            f"[1:a]aresample=44100,apad,atrim=0:{duration_seconds:.3f},asetpts=PTS-STARTPTS[a]"
        )
        command = [
            self.tools.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{self.settings.video_width}x{self.settings.video_height}",
            "-r",
            str(self.settings.video_fps),
            "-i",
            "pipe:0",
            "-i",
            str(audio_path),
            "-filter_complex",
            audio_filter,
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-t",
            f"{duration_seconds:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            self.preset,
            "-crf",
            str(self.crf),
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(max(1, self.settings.video_fps * 2)),
            "-c:a",
            "aac",
            "-b:a",
            self.audio_bitrate,
            "-ar",
            "44100",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
        ]
        if self.settings.ffmpeg_threads > 0:
            command.extend(["-threads", str(self.settings.ffmpeg_threads)])
        command.append(str(output_path))

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=_no_window_flags(),
        )
        try:
            assert process.stdin is not None
            for frame in frames:
                if time.monotonic() > deadline:
                    raise JobTimeoutError(self.settings.job_timeout_seconds, "scene_rendering")
                process.stdin.write(frame)
            process.stdin.close()
            wait_timeout = max(1.0, deadline - time.monotonic())
            return_code = process.wait(timeout=wait_timeout)
        except BrokenPipeError as exc:
            stderr = _read_stderr(process)
            raise RenderError(
                f"FFmpeg stopped while accepting scene frames: {stderr[-400:]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait(timeout=10)
            raise JobTimeoutError(self.settings.job_timeout_seconds, "scene_rendering") from exc
        except Exception:
            process.kill()
            process.wait(timeout=10)
            raise
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            if process.stdin and not process.stdin.closed:
                process.stdin.close()

        stderr_text = _read_stderr(process)
        if return_code != 0:
            output_path.unlink(missing_ok=True)
            raise RenderError(f"FFmpeg scene encoding failed: {stderr_text[-500:]}")
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RenderError("FFmpeg reported success but the scene file is missing.")
        return output_path

    def concat_scenes(
        self,
        scene_paths: list[Path],
        output_path: Path,
        *,
        concat_dir: Path,
        deadline: float,
    ) -> Path:
        if not scene_paths:
            raise RenderError("No rendered scenes to concatenate.")
        concat_dir.mkdir(parents=True, exist_ok=True)
        concat_file = concat_dir / "concat.txt"
        lines = []
        for path in scene_paths:
            escaped = path.resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        remaining = max(1.0, deadline - time.monotonic())
        copy_command = [
            self.tools.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        try:
            completed = subprocess.run(
                copy_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(self.settings.ffmpeg_timeout_seconds, remaining),
                check=False,
                creationflags=_no_window_flags(),
            )
            if completed.returncode == 0 and output_path.is_file():
                return output_path
        except (OSError, subprocess.TimeoutExpired):
            pass

        # Codec parameters should match, but re-encode defensively if stream copy
        # fails (for example after an FFmpeg upgrade).
        output_path.unlink(missing_ok=True)
        remaining = max(1.0, deadline - time.monotonic())
        reencode_command = [
            self.tools.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            self.preset,
            "-crf",
            str(self.crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            self.audio_bitrate,
            "-ar",
            "44100",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        try:
            completed = subprocess.run(
                reencode_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(self.settings.ffmpeg_timeout_seconds, remaining),
                check=False,
                creationflags=_no_window_flags(),
            )
        except subprocess.TimeoutExpired as exc:
            output_path.unlink(missing_ok=True)
            raise JobTimeoutError(self.settings.job_timeout_seconds, "video_composition") from exc
        if completed.returncode != 0 or not output_path.is_file():
            output_path.unlink(missing_ok=True)
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RenderError(f"FFmpeg concatenation failed: {detail[-500:]}")
        return output_path


def _read_stderr(process: subprocess.Popen[bytes]) -> str:
    if process.stderr is None:
        return ""
    try:
        return process.stderr.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def ensure_output_parent(path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def atomic_copy(source: Path, destination: Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with Path(source).open("rb") as reader, temp.open("wb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination
