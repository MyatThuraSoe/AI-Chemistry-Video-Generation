"""TTS provider exports.

Provider implementations live in :mod:`app.generation.audio_provider`, together
with narration caching and audio validation. This module keeps the provider
namespace described by the project layout stable for integrations.
"""

from app.generation.audio_provider import (
    CachedNarrationProvider,
    EspeakNarrationProvider,
    NarrationProvider,
    OpenAINarrationProvider,
    PlaceholderNarrationProvider,
    UnavailableNarrationProvider,
    WindowsSapiNarrationProvider,
    build_narration_provider,
)

__all__ = [
    "CachedNarrationProvider",
    "EspeakNarrationProvider",
    "NarrationProvider",
    "OpenAINarrationProvider",
    "PlaceholderNarrationProvider",
    "UnavailableNarrationProvider",
    "WindowsSapiNarrationProvider",
    "build_narration_provider",
]
