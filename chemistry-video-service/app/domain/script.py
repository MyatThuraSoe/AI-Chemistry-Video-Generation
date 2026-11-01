"""Content schema shared by curated scripts and optional LLM-generated scripts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScriptScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: int
    layout: str
    narration: str
    visual_description: str
    on_screen_labels: list[str] = Field(default_factory=list)


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: str
    title: str
    summary: str
    target_duration_seconds: float
    scenes: list[ScriptScene]


class ConceptPack(BaseModel):
    """A content pack for one concept.

    Add new concepts by creating another pack (see ``app/generation/content``)
    and registering it with :class:`ConceptRegistry`.
    """

    model_config = ConfigDict(extra="forbid")

    concept_id: str
    aliases: list[str]
    required_terms: list[str]
    min_duration_seconds: float
    max_duration_seconds: float
    script: Script
    content_version: str = "1.0.0"


class ScriptValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    word_count: int = 0
    estimated_duration_seconds: float = 0.0
    scene_estimates: dict[int, float] = Field(default_factory=dict)

    @property
    def summary_message(self) -> str:
        if self.valid:
            return "Script validation passed."
        return "; ".join(self.errors)
