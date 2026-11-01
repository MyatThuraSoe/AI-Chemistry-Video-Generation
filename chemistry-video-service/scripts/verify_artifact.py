"""Verify a generated MP4 with FFprobe.

Checks that the file exists, has a video stream and an audio stream, and that
its duration is at least ``--min-duration`` seconds (default 10).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import Settings
from app.generation.providers.ffmpeg import FFmpegTools, FFprobeError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Path to the MP4 file to verify")
    parser.add_argument(
        "--min-duration",
        type=float,
        default=10.0,
        help="Minimum acceptable duration in seconds (default: 10)",
    )
    args = parser.parse_args(argv)

    path: Path = args.path
    if not path.is_file():
        print(f"ERROR: file does not exist: {path}", file=sys.stderr)
        return 1
    if path.stat().st_size <= 0:
        print(f"ERROR: file is empty: {path}", file=sys.stderr)
        return 1

    tools = FFmpegTools(Settings(app_env="local"))
    try:
        probe = tools.probe(path)
    except FFprobeError as exc:
        print(f"ERROR: FFprobe could not parse {path}: {exc}", file=sys.stderr)
        return 1

    video = probe.video_stream
    audio = probe.audio_stream
    duration = probe.duration_seconds

    if video is None:
        print("ERROR: no video stream found.", file=sys.stderr)
        return 1
    if audio is None:
        print("ERROR: no audio stream found.", file=sys.stderr)
        return 1
    if duration < args.min_duration:
        print(
            f"ERROR: duration {duration:.2f}s is below the {args.min_duration:.2f}s minimum.",
            file=sys.stderr,
        )
        return 1

    width = video.width or 0
    height = video.height or 0
    print(f"File:        {path.resolve()}")
    print(f"Size:        {path.stat().st_size / (1024 * 1024):.2f} MiB")
    print(f"Format:      {probe.format.format_name or 'unknown'}")
    print(f"Video:       {video.codec_name or 'unknown'} {width}x{height} @ {probe.fps:.2f} fps")
    print(
        "Audio:       "
        f"{audio.codec_name or 'unknown'} "
        f"{audio.sample_rate or '?'} Hz / {audio.channels or '?'} channel(s)"
    )
    print(f"Duration:    {duration:.2f}s")
    print("Result:      OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
