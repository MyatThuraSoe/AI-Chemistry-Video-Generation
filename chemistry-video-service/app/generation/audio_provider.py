"""Narration providers, caching and deterministic audio validation."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import shutil
import subprocess
import sys
import wave
from abc import ABC, abstractmethod
from array import array
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from app.config import Settings
from app.domain.errors import AudioValidationError, NarrationGenerationError
from app.generation.providers.ffmpeg import FFmpegTools, FFprobeError, _no_window_flags
from app.generation.script_validator import count_words

logger = logging.getLogger(__name__)

MIN_AUDIO_SECONDS = 0.3
SILENCE_THRESHOLD_DB = -60.0
DEFAULT_VOICE = "default"
PLACEHOLDER_PROVIDER = "mock"


class AudioResult(BaseModel):
    file_path: Path
    duration_seconds: float
    provider: str
    is_placeholder: bool
    sample_rate: int | None
    checksum_sha256: str
    source_provider: str | None = None
    cache_hit: bool = False
    voice: str | None = None


class AudioValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    sample_rate: int | None = None
    channels: int | None = None
    mean_volume_db: float | None = None
    file_size_bytes: int = 0
    checksum_sha256: str = ""

    @property
    def message(self) -> str:
        return "; ".join(self.errors) if self.errors else "Audio validation passed."


class NarrationProvider(ABC):
    name: str = "base"
    is_placeholder: bool = False

    @abstractmethod
    def generate(self, text: str, voice: str | None = None) -> AudioResult: ...

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def close(self) -> None:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_audio_file(
    path: Path,
    tools: FFmpegTools,
    *,
    allow_silence: bool = False,
) -> AudioValidationResult:
    path = Path(path)
    errors: list[str] = []
    warnings: list[str] = []

    if not path.is_file():
        return AudioValidationResult(valid=False, errors=["Audio file does not exist."])
    size = path.stat().st_size
    if size <= 0:
        errors.append("Audio file is empty.")
    elif size < 2048:
        warnings.append("Audio file is unusually small.")

    duration = 0.0
    sample_rate: int | None = None
    channels: int | None = None
    mean_volume: float | None = None
    try:
        probe = tools.probe(path)
    except FFprobeError as exc:
        errors.append(f"Audio could not be parsed by FFprobe: {exc}")
    else:
        audio_stream = probe.audio_stream
        if audio_stream is None:
            errors.append("Audio stream is missing.")
        else:
            duration = probe.duration_seconds
            try:
                sample_rate = int(audio_stream.sample_rate) if audio_stream.sample_rate else None
            except ValueError:
                sample_rate = None
            channels = audio_stream.channels
            if duration <= MIN_AUDIO_SECONDS:
                errors.append(
                    f"Audio duration {duration:.2f}s must be greater than {MIN_AUDIO_SECONDS}s."
                )
            if sample_rate is not None and not (8_000 <= sample_rate <= 96_000):
                errors.append(f"Unsupported audio sample rate: {sample_rate} Hz.")
            if channels is not None and channels < 1:
                errors.append("Audio has no channels.")
            try:
                mean_volume = tools.mean_volume_db(path)
            except (RuntimeError, OSError):
                warnings.append("Could not measure audio volume.")
            if (
                not allow_silence
                and mean_volume is not None
                and mean_volume <= SILENCE_THRESHOLD_DB
            ):
                errors.append(f"Audio is silent (mean volume {mean_volume:.1f} dB).")

    checksum = sha256_file(path) if path.is_file() else ""
    return AudioValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        duration_seconds=round(duration, 3),
        sample_rate=sample_rate,
        channels=channels,
        mean_volume_db=mean_volume,
        file_size_bytes=size,
        checksum_sha256=checksum,
    )


def require_valid_audio(
    path: Path,
    tools: FFmpegTools,
    *,
    allow_silence: bool = False,
) -> AudioValidationResult:
    result = validate_audio_file(path, tools, allow_silence=allow_silence)
    if not result.valid:
        raise AudioValidationError(
            f"Narration audio failed validation: {result.message}",
            details={"errors": result.errors, "warnings": result.warnings},
        )
    return result


def _result_from_file(
    path: Path,
    *,
    provider: str,
    is_placeholder: bool,
    tools: FFmpegTools,
    voice: str | None,
    source_provider: str | None = None,
    cache_hit: bool = False,
) -> AudioResult:
    validation = require_valid_audio(path, tools, allow_silence=is_placeholder)
    return AudioResult(
        file_path=path,
        duration_seconds=validation.duration_seconds,
        provider=provider,
        is_placeholder=is_placeholder,
        sample_rate=validation.sample_rate,
        checksum_sha256=validation.checksum_sha256,
        source_provider=source_provider,
        cache_hit=cache_hit,
        voice=voice,
    )


def _write_placeholder_wave(text: str, output: Path, *, sample_rate: int = 22_050) -> float:
    """Write an audible, clearly synthetic placeholder track and return its duration."""
    word_count = max(1, count_words(text))
    duration = max(1.2, word_count / 2.6 + 0.5)
    total_samples = int(duration * sample_rate)
    samples = array("h", [0]) * total_samples

    gap = 0.055
    word_span = duration / word_count
    for index in range(total_samples):
        t = index / sample_rate
        word_index = min(word_count - 1, int(t / word_span))
        within = t - word_index * word_span
        tone_duration = max(0.05, word_span - gap)
        if within >= tone_duration:
            continue
        envelope = math.sin(math.pi * within / tone_duration) ** 2
        frequency = 170.0 + (word_index * 29) % 110
        value = (
            0.20 * math.sin(2 * math.pi * frequency * within)
            + 0.06 * math.sin(2 * math.pi * frequency * 2 * within)
        ) * envelope
        samples[index] = max(-32767, min(32767, int(value * 32767)))

    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return duration


class PlaceholderNarrationProvider(NarrationProvider):
    name = PLACEHOLDER_PROVIDER
    is_placeholder = True

    def __init__(self, settings: Settings, tools: FFmpegTools) -> None:
        self.settings = settings
        self.tools = tools
        self.temp_dir = settings.data_dir / "tts_tmp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, text: str, voice: str | None = None) -> AudioResult:
        if not text.strip():
            raise NarrationGenerationError("Cannot synthesize empty narration.")
        key = hashlib.sha256(
            f"{text}\x00{voice or DEFAULT_VOICE}\x00placeholder".encode()
        ).hexdigest()[:24]
        output = self.temp_dir / f"placeholder_{key}.wav"
        if not output.is_file():
            _write_placeholder_wave(text, output)
        return _result_from_file(
            output,
            provider=self.name,
            is_placeholder=True,
            tools=self.tools,
            voice=voice,
            source_provider=self.name,
        )


class UnavailableNarrationProvider(NarrationProvider):
    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def generate(self, text: str, voice: str | None = None) -> AudioResult:
        raise NarrationGenerationError(
            f"No narration provider is available: {self.reason}",
            retryable=False,
        )


class WindowsSapiNarrationProvider(NarrationProvider):
    name = "windows_sapi"

    def __init__(self, settings: Settings, tools: FFmpegTools) -> None:
        if sys.platform != "win32":
            raise RuntimeError("TTS_PROVIDER=windows_sapi is only available on Windows")
        self.settings = settings
        self.tools = tools
        self.temp_dir = settings.data_dir / "tts_tmp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not self.powershell:
            fallback = (
                Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
                / "System32/WindowsPowerShell/v1.0/powershell.exe"
            )
            if fallback.is_file():
                self.powershell = str(fallback)
        if not self.powershell:
            raise RuntimeError("Windows SAPI narration requires powershell.exe")
        self.script = Path(__file__).parent / "providers" / "sapi_tts.ps1"
        if not self.script.is_file():
            raise RuntimeError(f"SAPI helper script is missing: {self.script}")

    def generate(self, text: str, voice: str | None = None) -> AudioResult:
        if not text.strip():
            raise NarrationGenerationError("Cannot synthesize empty narration.")
        key = hashlib.sha256(
            f"{text}\x00{voice or DEFAULT_VOICE}\x00sapi{self.settings.tts_rate}".encode()
        ).hexdigest()[:24]
        text_file = self.temp_dir / f"sapi_{key}.txt"
        output = self.temp_dir / f"sapi_{key}.wav"
        text_file.write_text(text, encoding="utf-8")
        if not output.is_file() or output.stat().st_size == 0:
            command = [
                str(self.powershell),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script),
                "-TextFile",
                str(text_file),
                "-OutputFile",
                str(output),
                "-Rate",
                str(self.settings.tts_rate),
                "-Voice",
                voice or "",
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                    check=False,
                    creationflags=_no_window_flags(),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise NarrationGenerationError(
                    f"Windows SAPI synthesis failed to start: {exc}", retryable=True
                ) from exc
            if completed.returncode != 0 or not output.is_file():
                detail = (completed.stderr or completed.stdout or "").strip()[-300:]
                raise NarrationGenerationError(
                    f"Windows SAPI synthesis failed: {detail or 'unknown error'}",
                    retryable=True,
                )
        return _result_from_file(
            output,
            provider=self.name,
            is_placeholder=False,
            tools=self.tools,
            voice=voice,
            source_provider=self.name,
        )


class EspeakNarrationProvider(NarrationProvider):
    name = "espeak"

    def __init__(self, settings: Settings, tools: FFmpegTools) -> None:
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if not binary:
            raise RuntimeError("TTS_PROVIDER=espeak requires espeak-ng on PATH")
        self.binary = binary
        self.settings = settings
        self.tools = tools
        self.temp_dir = settings.data_dir / "tts_tmp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, text: str, voice: str | None = None) -> AudioResult:
        if not text.strip():
            raise NarrationGenerationError("Cannot synthesize empty narration.")
        key = hashlib.sha256(
            f"{text}\x00{voice or DEFAULT_VOICE}\x00espeak{self.settings.tts_espeak_wpm}".encode()
        ).hexdigest()[:24]
        output = self.temp_dir / f"espeak_{key}.wav"
        if not output.is_file() or output.stat().st_size == 0:
            command = [
                self.binary,
                "-v",
                voice or "en",
                "-s",
                str(self.settings.tts_espeak_wpm),
                "-w",
                str(output),
                text,
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    check=False,
                    creationflags=_no_window_flags(),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise NarrationGenerationError(
                    f"espeak synthesis failed to start: {exc}", retryable=True
                ) from exc
            if completed.returncode != 0 or not output.is_file():
                detail = (completed.stderr or completed.stdout or "").strip()[-300:]
                raise NarrationGenerationError(
                    f"espeak synthesis failed: {detail or 'unknown error'}", retryable=True
                )
        return _result_from_file(
            output,
            provider=self.name,
            is_placeholder=False,
            tools=self.tools,
            voice=voice,
            source_provider=self.name,
        )


class OpenAINarrationProvider(NarrationProvider):
    name = "openai"

    def __init__(self, settings: Settings, tools: FFmpegTools) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("TTS_PROVIDER=openai requires OPENAI_API_KEY")
        self.settings = settings
        self.tools = tools
        self.temp_dir = settings.data_dir / "tts_tmp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, text: str, voice: str | None = None) -> AudioResult:
        if not text.strip():
            raise NarrationGenerationError("Cannot synthesize empty narration.")
        selected_voice = voice or "alloy"
        key = hashlib.sha256(
            f"{text}\x00{selected_voice}\x00{self.settings.openai_tts_model}".encode()
        ).hexdigest()[:24]
        output = self.temp_dir / f"openai_{key}.wav"
        if not output.is_file() or output.stat().st_size == 0:
            url = self.settings.openai_tts_base_url.rstrip("/") + "/audio/speech"
            headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
            payload = {
                "model": self.settings.openai_tts_model,
                "input": text,
                "voice": selected_voice,
                "response_format": "wav",
            }
            try:
                with httpx.Client(timeout=90.0) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
            except httpx.HTTPError as exc:
                raise NarrationGenerationError(
                    f"OpenAI TTS request failed: {exc}", retryable=True
                ) from exc
            output.write_bytes(response.content)
        return _result_from_file(
            output,
            provider=self.name,
            is_placeholder=False,
            tools=self.tools,
            voice=selected_voice,
            source_provider=self.name,
        )


class CachedNarrationProvider(NarrationProvider):
    """Cache narration by ``sha256(text + voice + provider)``.

    Optionally checks a read-only asset directory first, which is how the
    pre-generated canonical narration ships with the repository.
    """

    def __init__(
        self,
        inner: NarrationProvider,
        *,
        cache_dir: Path,
        namespace: str,
        tools: FFmpegTools,
        default_voice: str,
        asset_dirs: tuple[Path, ...] = (),
    ) -> None:
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.name = namespace
        self.tools = tools
        self.default_voice = default_voice or DEFAULT_VOICE
        self.asset_dirs = tuple(Path(path) for path in asset_dirs)
        self.is_placeholder = inner.is_placeholder

    @staticmethod
    def cache_key(text: str, voice: str, namespace: str) -> str:
        return hashlib.sha256(f"{text}\x00{voice}\x00{namespace}".encode()).hexdigest()

    def available(self) -> tuple[bool, str]:
        return self.inner.available()

    def _candidate_paths(self, key: str) -> list[Path]:
        return [directory / f"{key}.wav" for directory in (*self.asset_dirs, self.cache_dir)]

    def generate(self, text: str, voice: str | None = None) -> AudioResult:
        if not text.strip():
            raise NarrationGenerationError("Cannot synthesize empty narration.")
        selected_voice = voice or self.default_voice
        key = self.cache_key(text, selected_voice, self.name)
        for candidate in self._candidate_paths(key):
            if not candidate.is_file():
                continue
            try:
                return _result_from_file(
                    candidate,
                    provider=self.name,
                    is_placeholder=False,
                    tools=self.tools,
                    voice=selected_voice,
                    source_provider="cache",
                    cache_hit=True,
                )
            except AudioValidationError as exc:
                logger.warning(
                    "Discarding invalid cached narration",
                    extra={
                        "event": "audio_cache_invalid",
                        "path": str(candidate),
                        "error": exc.message,
                    },
                )
                if candidate.is_relative_to(self.cache_dir):
                    candidate.unlink(missing_ok=True)

        result = self.inner.generate(text, selected_voice)
        require_valid_audio(result.file_path, self.tools, allow_silence=result.is_placeholder)
        if result.is_placeholder:
            return result

        destination = self.cache_dir / f"{key}.wav"
        temp = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            shutil.copyfile(result.file_path, temp)
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)
        return AudioResult(
            file_path=destination,
            duration_seconds=result.duration_seconds,
            provider=self.name,
            is_placeholder=result.is_placeholder,
            sample_rate=result.sample_rate,
            checksum_sha256=sha256_file(destination),
            source_provider=result.source_provider or result.provider,
            cache_hit=False,
            voice=selected_voice,
        )


def build_narration_provider(settings: Settings, tools: FFmpegTools) -> NarrationProvider:
    """Build the configured provider chain.

    ``canonical_cache`` first serves pre-generated files, then falls back to a
    local TTS engine when available. Missing local engines are not fatal at
    startup because every canonical scene ships with cached narration.
    """
    cache_dir = settings.narration_cache_dir or (settings.data_dir / "narration_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    voice = settings.tts_voice

    if settings.tts_provider == "mock":
        return PlaceholderNarrationProvider(settings, tools)

    if settings.tts_provider in {"canonical_cache", "windows_sapi", "espeak", "openai"}:
        inner: NarrationProvider
        if settings.tts_provider == "openai":
            inner = OpenAINarrationProvider(settings, tools)
        elif settings.tts_provider == "espeak":
            inner = EspeakNarrationProvider(settings, tools)
        elif settings.tts_provider == "windows_sapi":
            inner = WindowsSapiNarrationProvider(settings, tools)
        else:
            espeak_available = bool(shutil.which("espeak-ng") or shutil.which("espeak"))
            if espeak_available:
                inner = EspeakNarrationProvider(settings, tools)
            elif sys.platform == "win32":
                inner = WindowsSapiNarrationProvider(settings, tools)
            else:
                inner = UnavailableNarrationProvider(
                    "install espeak-ng or provide pre-generated canonical narration assets"
                )

        return CachedNarrationProvider(
            inner,
            cache_dir=cache_dir,
            namespace=settings.tts_provider,
            tools=tools,
            default_voice=voice,
            asset_dirs=(settings.narration_assets_dir,),
        )

    raise RuntimeError(f"Unsupported TTS provider: {settings.tts_provider}")


def cache_key_for_asset(text: str, voice: str, namespace: str = "canonical_cache") -> str:
    return CachedNarrationProvider.cache_key(text, voice or DEFAULT_VOICE, namespace)


def generate_placeholder_for_test(text: str, output_dir: Path) -> Path:
    """Expose the placeholder generator for tests and tooling."""
    output = Path(output_dir) / f"placeholder_{hashlib.sha256(text.encode()).hexdigest()[:16]}.wav"
    _write_placeholder_wave(text, output)
    return output


__all__ = [
    "AudioResult",
    "AudioValidationResult",
    "CachedNarrationProvider",
    "EspeakNarrationProvider",
    "NarrationProvider",
    "OpenAINarrationProvider",
    "PlaceholderNarrationProvider",
    "UnavailableNarrationProvider",
    "WindowsSapiNarrationProvider",
    "build_narration_provider",
    "cache_key_for_asset",
    "generate_placeholder_for_test",
    "require_valid_audio",
    "sha256_file",
    "validate_audio_file",
]
