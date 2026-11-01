"""Optional LLM script generation behind a validated interface.

The default content policy is canonical-only. This adapter is used only when
``SCRIPT_SOURCE=canonical_with_llm_fallback`` and never bypasses validation.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

import httpx

from app.config import Settings
from app.domain.errors import ScriptGenerationError
from app.domain.script import ConceptPack, Script


class ScriptGenerationProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, pack: ConceptPack, previous_errors: list[str] | None = None) -> Script: ...


class MockLLMScriptProvider(ScriptGenerationProvider):
    """Deterministic stand-in used to exercise the fallback path in tests."""

    name = "mock_llm"

    def generate(self, pack: ConceptPack, previous_errors: list[str] | None = None) -> Script:
        del previous_errors
        return pack.script.model_copy(deep=True)


class OpenAICompatibleScriptProvider(ScriptGenerationProvider):
    name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is required for LLM_PROVIDER=openai_compatible")
        self.settings = settings

    def generate(self, pack: ConceptPack, previous_errors: list[str] | None = None) -> Script:
        script_schema = {
            "concept_id": "string",
            "title": "string",
            "summary": "string",
            "target_duration_seconds": 0,
            "scenes": [
                {
                    "scene_id": 1,
                    "layout": "string",
                    "narration": "string",
                    "visual_description": "string",
                    "on_screen_labels": ["string"],
                }
            ],
        }
        feedback = ""
        if previous_errors:
            feedback = "\nFix these validation errors:\n- " + "\n- ".join(previous_errors)
        prompt = (
            f"Write a short educational video script for the concept '{pack.script.title}'.\n"
            f"Required terms: {', '.join(pack.required_terms)}.\n"
            f"Use {len(pack.script.scenes)} scenes, 4 to 10 scenes total.\n"
            f"Target narration duration: {pack.script.target_duration_seconds} seconds "
            f"(acceptable range {pack.min_duration_seconds}-{pack.max_duration_seconds}s).\n"
            "Each scene needs narration, a visual_description, and 1-4 on-screen labels.\n"
            "Avoid absolute claims, dangerous instructions, and irrelevant content.\n"
            "Use simple language for beginners. Keep each scene under 20 seconds.\n"
            "Return JSON only, matching this schema exactly:\n"
            f"{json.dumps(script_schema, indent=2)}{feedback}"
        )
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a careful chemistry curriculum writer. "
                        "You return only valid JSON and never invent unsupported claims."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        try:
            with httpx.Client(timeout=90.0) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ScriptGenerationError(
                f"LLM script request failed: {exc}", retryable=True
            ) from exc

        try:
            raw = _strip_code_fence(str(content))
            script = Script.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ScriptGenerationError(
                f"LLM returned invalid script JSON: {exc}", retryable=True
            ) from exc
        return script


def _strip_code_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def build_script_provider(settings: Settings) -> ScriptGenerationProvider | None:
    """Return an LLM provider only when the configured policy allows it."""
    if settings.script_source != "canonical_with_llm_fallback":
        return None
    if settings.llm_provider == "mock":
        return MockLLMScriptProvider()
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleScriptProvider(settings)
    return None
