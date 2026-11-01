"""Small, safe wrappers around FFmpeg and FFprobe.

Commands are always executed as argument lists (never through a shell), with
explicit timeouts. FFprobe JSON is parsed into typed models.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import PROJECT_ROOT, Settings


class FFprobeError(RuntimeError):
    """FFprobe failed or could not parse a media file."""


class ProbeStream(BaseModel):
    index: int = 0
    codec_type: str | None = None
    codec_name: str | None = None
    width: int | None = None
    height: int | None = None
    sample_rate: str | None = None
    channels: int | None = None
    duration: str | None = None
    r_frame_rate: str | None = None
    avg_frame_rate: str | None = None


class ProbeFormat(BaseModel):
    duration: str | None = None
    size: str | None = None
    format_name: str | None = None


class ProbeResult(BaseModel):
    streams: list[ProbeStream] = Field(default_factory=list)
    format: ProbeFormat = Field(default_factory=ProbeFormat)

    @property
    def video_stream(self) -> ProbeStream | None:
        return next((s for s in self.streams if s.codec_type == "video"), None)

    @property
    def audio_stream(self) -> ProbeStream | None:
        return next((s for s in self.streams if s.codec_type == "audio"), None)

    @property
    def duration_seconds(self) -> float:
        candidates: list[float] = []
        for value in [self.format.duration, *(stream.duration for stream in self.streams)]:
            try:
                if value is not None:
                    candidates.append(float(value))
            except ValueError:
                continue
        return max(candidates) if candidates else 0.0

    @property
    def size_bytes(self) -> int:
        try:
            return int(self.format.size or 0)
        except ValueError:
            return 0

    @property
    def fps(self) -> float:
        stream = self.video_stream
        raw = stream.avg_frame_rate or stream.r_frame_rate or "0/1" if stream else "0/1"
        try:
            numerator, denominator = raw.split("/", maxsplit=1)
            return float(numerator) / float(denominator) if float(denominator) else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0


class FFmpegTools:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._ffmpeg: str | None = None
        self._ffprobe: str | None = None

    @property
    def ffmpeg_binary(self) -> str:
        if self._ffmpeg is None:
            self._ffmpeg = self._resolve_binary(self.settings.ffmpeg_binary, "ffmpeg")
        return self._ffmpeg

    @property
    def ffprobe_binary(self) -> str:
        if self._ffprobe is None:
            self._ffprobe = self._resolve_binary(self.settings.ffprobe_binary, "ffprobe")
        return self._ffprobe

    def _resolve_binary(self, configured: str, tool: str) -> str:
        candidate = Path(configured)
        if (
            candidate.is_absolute()
            or os.sep in configured
            or (os.altsep and os.altsep in configured)
        ):
            if candidate.is_file():
                return str(candidate)
            return configured

        found = shutil.which(configured)
        if found:
            return found

        exe_name = f"{tool}.exe" if sys.platform == "win32" else tool
        search_roots: list[Path] = [
            PROJECT_ROOT / "tools" / "ffmpeg" / "bin",
            Path("/usr/local/bin"),
            Path("/usr/bin"),
        ]
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            winget_root = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
            if winget_root.is_dir():
                search_roots.extend(
                    sorted(winget_root.glob("Gyan.FFmpeg*/**/bin"), reverse=True)[:4]
                )
        search_roots.extend([Path("C:/ffmpeg/bin")])
        for root in search_roots:
            direct = root / exe_name
            if direct.is_file():
                return str(direct)

        return configured

    def check_ffmpeg(self) -> tuple[bool, str]:
        return self._check_tool(self.ffmpeg_binary, "-version")

    def check_ffprobe(self) -> tuple[bool, str]:
        return self._check_tool(self.ffprobe_binary, "-version")

    @staticmethod
    def _check_tool(binary: str, flag: str) -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                [binary, flag],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                creationflags=_no_window_flags(),
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            return False, f"{Path(binary).name} unavailable: {exc}"
        if completed.returncode != 0:
            return False, f"{Path(binary).name} exited with {completed.returncode}"
        first_line = (completed.stdout or completed.stderr or "").splitlines()
        return True, first_line[0] if first_line else "ok"

    def run(
        self,
        args: list[str],
        *,
        timeout: float,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [self.ffmpeg_binary, *args]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=_no_window_flags(),
        )
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            tail = " | ".join(detail[-4:])
            raise RuntimeError(f"FFmpeg failed ({completed.returncode}): {tail}")
        return completed

    def probe(self, path: Path, *, timeout: float = 30.0) -> ProbeResult:
        path = Path(path)
        if not path.is_file():
            raise FFprobeError(f"Media file does not exist: {path}")
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=_no_window_flags(),
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            raise FFprobeError(f"FFprobe could not run: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise FFprobeError(f"FFprobe could not parse {path.name}: {detail[-500:]}")
        try:
            payload: dict[str, Any] = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise FFprobeError(f"FFprobe returned invalid JSON for {path.name}") from exc
        return ProbeResult.model_validate(payload)

    def mean_volume_db(self, path: Path, *, timeout: float = 60.0) -> float | None:
        """Return the mean audio volume in dB, or ``None`` if it cannot be read."""
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=_no_window_flags(),
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None
        for line in (completed.stderr or "").splitlines():
            marker = "mean_volume:"
            if marker in line:
                try:
                    return float(line.split(marker, maxsplit=1)[1].replace("dB", "").strip())
                except ValueError:
                    return None
        return None

    def duration_seconds(self, path: Path) -> float:
        try:
            return self.probe(path).duration_seconds
        except FFprobeError:
            return 0.0


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0
