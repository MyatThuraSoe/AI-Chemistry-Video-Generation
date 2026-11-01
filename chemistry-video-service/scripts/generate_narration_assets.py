"""Pre-generate canonical narration WAV assets with Windows SAPI.

The production default (``TTS_PROVIDER=canonical_cache``) serves these files
before falling back to a local speech engine, so the service does not depend on
network access or a runtime TTS install for the three required concepts.

Usage (Windows)::

    python scripts/generate_narration_assets.py --force

The script writes ``assets/narration/<sha256>.wav`` using the same cache key as
:class:`app.generation.audio_provider.CachedNarrationProvider`, then verifies
that every canonical scene is served from the asset directory.
"""

from __future__ import annotations

import argparse
import shutil
import sys

from app.config import Settings
from app.generation.audio_provider import (
    CachedNarrationProvider,
    WindowsSapiNarrationProvider,
    cache_key_for_asset,
    require_valid_audio,
)
from app.generation.content import load_concept_packs
from app.generation.providers.ffmpeg import FFmpegTools


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate and overwrite assets even when they already exist.",
    )
    parser.add_argument(
        "--voice",
        default="",
        help="Optional SAPI voice name. The default system voice is used when omitted.",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        print("This helper uses Windows SAPI and only runs on Windows.", file=sys.stderr)
        return 2

    settings = Settings(app_env="local")
    settings.ensure_directories()
    tools = FFmpegTools(settings)
    ok, detail = tools.check_ffprobe()
    if not ok:
        print(f"ffprobe is unavailable: {detail}", file=sys.stderr)
        return 2

    voice_label = args.voice or "default"
    provider = WindowsSapiNarrationProvider(settings, tools)
    output_dir = settings.narration_assets_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0
    seen: set[str] = set()
    for pack in load_concept_packs():
        for scene in pack.script.scenes:
            key = cache_key_for_asset(scene.narration, voice_label, "canonical_cache")
            if key in seen:
                continue
            seen.add(key)
            destination = output_dir / f"{key}.wav"
            if destination.is_file() and not args.force:
                skipped += 1
                continue

            result = provider.generate(scene.narration, args.voice or None)
            require_valid_audio(result.file_path, tools)
            temporary = destination.with_suffix(".wav.tmp")
            shutil.copyfile(result.file_path, temporary)
            temporary.replace(destination)
            created += 1
            print(
                f"{pack.concept_id} scene {scene.scene_id:02d}: "
                f"{result.duration_seconds:.2f}s -> {destination.name}"
            )

    cache = CachedNarrationProvider(
        provider,
        cache_dir=settings.narration_cache_dir or (settings.data_dir / "narration_cache"),
        namespace="canonical_cache",
        tools=tools,
        default_voice=voice_label,
        asset_dirs=(output_dir,),
    )
    verified = 0
    for pack in load_concept_packs():
        for scene in pack.script.scenes:
            result = cache.generate(scene.narration, args.voice or None)
            if not result.cache_hit:
                print(
                    f"ERROR: {pack.concept_id} scene {scene.scene_id} was not served "
                    "from the asset cache.",
                    file=sys.stderr,
                )
                return 1
            verified += 1

    print(
        f"Canonical narration assets: {created} generated, {skipped} skipped, "
        f"{verified} verified in {output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
