"""Deterministic Pillow + FFmpeg video renderer."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import UUID

from PIL import Image
from pydantic import BaseModel

from app.config import Settings
from app.domain.errors import JobTimeoutError, RenderError
from app.generation.providers.ffmpeg import FFmpegTools, FFprobeError
from app.generation.providers.ffmpeg_renderer import FFmpegSceneEncoder, atomic_copy
from app.generation.storyboard_builder import Storyboard, StoryboardScene
from app.generation.visuals.layouts import draw_scene_layout
from app.generation.visuals.theme import (
    PRIMARY,
    Canvas,
    FontManager,
    build_background,
    draw_caption,
    draw_header,
)
from app.storage.artifact_store import ArtifactStore

ProgressCallback = Callable[[float], None]


class RenderResult(BaseModel):
    video_path: Path
    duration_seconds: float
    resolution: str
    width: int
    height: int
    fps: float
    codec: str
    checksum_sha256: str
    subtitles_path: Path
    thumbnail_path: Path
    scene_count: int
    renderer: str = "pillow-ffmpeg"


class SceneRenderer(Protocol):
    def render(
        self,
        storyboard: Storyboard,
        *,
        job_id: UUID,
        store: ArtifactStore,
        deadline: float,
        progress: ProgressCallback | None = None,
    ) -> RenderResult: ...


class PillowFFmpegRenderer:
    """Render scenes to frames, encode with FFmpeg, concatenate and derive assets."""

    def __init__(self, settings: Settings, tools: FFmpegTools) -> None:
        self.settings = settings
        self.tools = tools
        self.encoder = FFmpegSceneEncoder(settings, tools)

    def render(
        self,
        storyboard: Storyboard,
        *,
        job_id: UUID,
        store: ArtifactStore,
        deadline: float,
        progress: ProgressCallback | None = None,
    ) -> RenderResult:
        if time.monotonic() > deadline:
            raise JobTimeoutError(self.settings.job_timeout_seconds, "scene_rendering")

        work_dir = store.work_dir(str(job_id))
        scenes_dir = work_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        fonts = FontManager(self.settings.assets_dir)
        background = build_background(self.settings.video_width, self.settings.video_height)
        black = Image.new("RGB", (self.settings.video_width, self.settings.video_height), (0, 0, 0))

        scene_paths: list[Path] = []
        total_scenes = len(storyboard.scenes)
        for index, scene in enumerate(storyboard.scenes):
            if time.monotonic() > deadline:
                raise JobTimeoutError(self.settings.job_timeout_seconds, "scene_rendering")
            audio_path = self._resolve_audio(work_dir, scene)
            output_path = scenes_dir / f"scene_{index + 1:03d}.mp4"

            def frames(
                scene: StoryboardScene = scene,
                index: int = index,
                audio_path: Path = audio_path,
            ) -> Iterator[bytes]:
                frame_total = self.encoder.frame_count(scene.duration_seconds)
                for frame_index in range(frame_total):
                    t = frame_index / max(1, frame_total - 1)
                    image = self._render_frame(
                        background,
                        black,
                        fonts,
                        scene,
                        concept_id=storyboard.concept_id,
                        concept_title=storyboard.title,
                        scene_index=index + 1,
                        total_scenes=total_scenes,
                        t=t,
                        elapsed=frame_index / self.settings.video_fps,
                    )
                    yield image.tobytes()

            self.encoder.encode_scene(
                frames(),
                audio_path,
                output_path,
                duration_seconds=scene.duration_seconds,
                deadline=deadline,
            )
            scene_paths.append(output_path)
            if progress:
                progress(min(0.85, (index + 1) / max(1, total_scenes) * 0.85))

        if time.monotonic() > deadline:
            raise JobTimeoutError(self.settings.job_timeout_seconds, "video_composition")

        final_work_path = work_dir / "final.mp4"
        self.encoder.concat_scenes(
            scene_paths,
            final_work_path,
            concat_dir=work_dir,
            deadline=deadline,
        )
        if progress:
            progress(0.9)

        video_path = store.path_for(str(job_id), "video.mp4")
        atomic_copy(final_work_path, video_path)

        subtitles_path = self._write_subtitles(store, str(job_id), storyboard)
        thumbnail_path = self._write_thumbnail(
            store,
            str(job_id),
            storyboard,
            fonts,
        )
        if progress:
            progress(1.0)

        try:
            probe = self.tools.probe(video_path)
        except FFprobeError as exc:
            raise RenderError(f"Rendered video could not be probed: {exc}") from exc
        video_stream = probe.video_stream
        if video_stream is None:
            raise RenderError("Rendered video has no video stream.")
        if probe.duration_seconds <= 0:
            raise RenderError("Rendered video has no measurable duration.")

        checksum = store.checksum_sha256(str(job_id), "video.mp4")
        return RenderResult(
            video_path=video_path,
            duration_seconds=round(probe.duration_seconds, 3),
            resolution=f"{video_stream.width}x{video_stream.height}",
            width=video_stream.width or self.settings.video_width,
            height=video_stream.height or self.settings.video_height,
            fps=round(probe.fps or self.settings.video_fps, 3),
            codec=video_stream.codec_name or "h264",
            checksum_sha256=checksum,
            subtitles_path=subtitles_path,
            thumbnail_path=thumbnail_path,
            scene_count=total_scenes,
        )

    def _resolve_audio(self, work_dir: Path, scene: StoryboardScene) -> Path:
        if not scene.audio_path:
            raise RenderError(f"Scene {scene.scene_id} has no narration audio path.")
        candidate = (work_dir / scene.audio_path).resolve()
        try:
            candidate.relative_to(work_dir.resolve())
        except ValueError as exc:
            raise RenderError(
                f"Scene {scene.scene_id} audio path escapes the work directory."
            ) from exc
        if not candidate.is_file():
            raise RenderError(f"Scene {scene.scene_id} narration file is missing.")
        return candidate

    def _render_frame(
        self,
        background: Image.Image,
        black: Image.Image,
        fonts: FontManager,
        scene: StoryboardScene,
        *,
        concept_id: str,
        concept_title: str,
        scene_index: int,
        total_scenes: int,
        t: float,
        elapsed: float,
    ) -> Image.Image:
        image = background.copy()
        canvas = Canvas(image, fonts)
        draw_header(canvas, concept_title, scene_index, total_scenes)
        draw_scene_layout(canvas, scene, t, concept_id)
        draw_caption(canvas, scene.caption_text)

        fade_duration = min(0.35, max(0.12, scene.duration_seconds * 0.05))
        fade = min(
            1.0,
            elapsed / fade_duration if fade_duration else 1.0,
            (scene.duration_seconds - elapsed) / fade_duration if fade_duration else 1.0,
        )
        if fade < 1.0:
            image = Image.blend(black, image, max(0.0, fade))
        return image

    def _write_subtitles(
        self,
        store: ArtifactStore,
        job_id: str,
        storyboard: Storyboard,
    ) -> Path:
        lines = ["WEBVTT", ""]
        cursor = 0.0
        for scene in storyboard.scenes:
            scene_end = cursor + scene.duration_seconds
            cue_end = min(
                scene_end,
                cursor + max(0.8, scene.narration_duration_seconds + 0.15),
            )
            lines.append(f"{_vtt_time(cursor)} --> {_vtt_time(cue_end)}")
            lines.append(scene.caption_text.strip())
            lines.append("")
            cursor = scene_end
        return store.write_text(job_id, "subtitles.vtt", "\n".join(lines))

    def _write_thumbnail(
        self,
        store: ArtifactStore,
        job_id: str,
        storyboard: Storyboard,
        fonts: FontManager,
    ) -> Path:
        background = build_background(self.settings.video_width, self.settings.video_height)
        image = background.copy()
        canvas = Canvas(image, fonts)
        first = storyboard.scenes[0] if storyboard.scenes else None
        if first is not None:
            draw_header(canvas, storyboard.title, 1, len(storyboard.scenes))
            draw_scene_layout(canvas, first, 1.0, storyboard.concept_id)
            canvas.pill(76, 636, "Short chemistry lesson", 20, outline=PRIMARY)
        else:
            canvas.text(640, 320, storyboard.title, 52, anchor="ma")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=90, optimize=True)
        return store.write_bytes(job_id, "thumbnail.jpg", buffer.getvalue())


def _vtt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
