"""Convert validated scripts into deterministic, renderable storyboards."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, Field

from app.domain.script import ConceptPack, Script
from app.generation.script_validator import (
    estimate_narration_seconds,
    estimate_scene_seconds,
)

MAX_SCENE_SECONDS = 20.0
SCENE_PADDING_SECONDS = 0.5


class Palette(BaseModel):
    primary: str
    background_start: str
    background_end: str
    text: str
    muted: str
    acid: str
    neutral: str
    base: str
    electron: str
    card: str


DEFAULT_PALETTE = Palette(
    primary="#4CC9F0",
    background_start="#050D1F",
    background_end="#0B2B52",
    text="#F8FAFC",
    muted="#A9B7CC",
    acid="#F94144",
    neutral="#90BE6D",
    base="#5B8DEF",
    electron="#FFD166",
    card="#102A4C",
)

LAYOUT_HEADINGS: dict[str, str] = {
    "title": "Chemistry, explained",
    "ph_scale_overview": "The pH scale: 0 to 14",
    "ph_regions": "Three regions of the scale",
    "hydrogen_ions": "Hydrogen ions and pH",
    "log_scale": "A logarithmic scale",
    "examples_on_scale": "pH in everyday life",
    "recap_list": "Quick recap",
    "valence_electrons": "Valence electrons",
    "electron_sharing": "Sharing electrons",
    "nonmetal_sharing": "Nonmetals share electrons",
    "h2_molecule": "A hydrogen molecule",
    "shared_attraction": "Held together by attraction",
    "ionic_transfer": "Electron transfer",
    "metal_nonmetal": "Metals and nonmetals",
    "ionic_ions": "Opposite charges attract",
    "salt_example": "Table salt",
    "covalent_share": "Sharing, not transferring",
    "molecule_example": "Water: a covalent molecule",
    "comparison_table": "Ionic vs covalent",
}

LAYOUT_DECORATIONS: dict[str, tuple[str, ...]] = {
    "title": ("concept_motif",),
    "ph_scale_overview": ("ph_scale",),
    "ph_regions": ("ph_scale", "region_bands"),
    "hydrogen_ions": ("ion_cloud",),
    "log_scale": ("step_highlight", "tenfold"),
    "examples_on_scale": ("ph_scale", "example_markers"),
    "recap_list": ("check_list", "mini_scale"),
    "valence_electrons": ("atom_with_shells",),
    "electron_sharing": ("two_atoms", "shared_pair"),
    "nonmetal_sharing": ("two_atoms", "bond_line"),
    "h2_molecule": ("two_atoms", "shared_pair", "formula"),
    "shared_attraction": ("two_atoms", "shared_pair", "attraction_arrows"),
    "ionic_transfer": ("two_atoms", "transfer_arrow"),
    "metal_nonmetal": ("two_atoms", "transfer_arrow"),
    "ionic_ions": ("two_ions", "attraction_arrows"),
    "salt_example": ("lattice", "formula"),
    "covalent_share": ("two_atoms", "shared_pair"),
    "molecule_example": ("water_molecule", "formula"),
    "comparison_table": ("comparison_table",),
}


class StoryboardElement(BaseModel):
    type: str
    value: str
    position: str
    size: str | None = None
    meta: dict[str, str] = Field(default_factory=dict)


class StoryboardScene(BaseModel):
    scene_id: int
    layout: str
    heading: str
    concept_title: str = ""
    concept_summary: str = ""
    duration_seconds: float
    narration_text: str
    caption_text: str
    visual_description: str
    background: str = "gradient_dark_blue"
    palette: Palette = DEFAULT_PALETTE
    elements: list[StoryboardElement]
    animation: str = "fade_and_slide"
    transition_out: str = "fade"
    narration_duration_seconds: float
    audio_path: str | None = None
    is_placeholder_audio: bool = False


class Storyboard(BaseModel):
    concept_id: str
    title: str
    summary: str
    script_source: str
    content_version: str
    target_duration_seconds: float
    min_duration_seconds: float
    max_duration_seconds: float
    total_duration_seconds: float
    scenes: list[StoryboardScene]


def _positions(count: int) -> list[str]:
    if count <= 1:
        return ["center"]
    if count == 2:
        return ["left", "right"]
    positions = ["left", "center", "right"]
    return [positions[min(index, 2)] for index in range(count)]


def _elements(layout: str, labels: list[str]) -> list[StoryboardElement]:
    elements: list[StoryboardElement] = []
    decorations = LAYOUT_DECORATIONS.get(layout, ())
    for decoration in decorations:
        elements.append(
            StoryboardElement(
                type="shape",
                value=decoration,
                position="center",
                meta={"layout": layout},
            )
        )
    positions = _positions(len(labels))
    for index, label in enumerate(labels):
        elements.append(
            StoryboardElement(
                type="text",
                value=label,
                position=positions[index],
                size="large" if index == 0 else "medium",
            )
        )
    return elements


def _stretch_to_target(
    durations: dict[int, float],
    *,
    minimum: float,
    maximum: float,
) -> dict[int, float]:
    """Add short holds so the video lands inside the concept's target window.

    Narration audio is never trimmed. Extra hold time is distributed evenly and
    capped per scene to avoid long, dead pauses.
    """
    durations = dict(durations)
    total = sum(durations.values())
    for _ in range(12):
        if total >= minimum:
            break
        adjustable = [
            scene_id for scene_id, value in durations.items() if value < MAX_SCENE_SECONDS
        ]
        if not adjustable:
            break
        deficit = minimum - total
        increment = min(deficit / len(adjustable), 1.5)
        for scene_id in adjustable:
            durations[scene_id] = min(MAX_SCENE_SECONDS, durations[scene_id] + increment)
        total = sum(durations.values())

    # If audio is unusually long, reduce only the synthetic hold (never below
    # narration + 0.2s), which keeps subtitles synchronized.
    if total > maximum:
        # Caller caps each scene at narration + padding already; this branch is a
        # safety net for future content packs.
        pass

    rounded = {scene_id: round(value, 3) for scene_id, value in durations.items()}
    # Rounding each scene independently can land a hair below the minimum
    # (e.g. 54.999 for a 55s target). Top up the first scene with headroom.
    total = round(sum(rounded.values()), 3)
    if total < minimum:
        deficit = round(minimum - total, 3)
        for scene_id in rounded:
            headroom = round(MAX_SCENE_SECONDS - rounded[scene_id], 3)
            if headroom <= 0:
                continue
            increment = min(deficit, headroom)
            rounded[scene_id] = round(rounded[scene_id] + increment, 3)
            deficit = round(deficit - increment, 3)
            if deficit <= 0:
                break
    return rounded


def build_storyboard(
    script: Script,
    pack: ConceptPack,
    *,
    audio_durations: Mapping[int, float] | None = None,
    audio_paths: Mapping[int, str] | None = None,
    placeholder_scene_ids: Mapping[int, bool] | None = None,
    script_source: str = "canonical",
) -> Storyboard:
    audio_durations = audio_durations or {}
    audio_paths = audio_paths or {}
    placeholder_scene_ids = placeholder_scene_ids or {}

    scenes: list[StoryboardScene] = []
    durations: dict[int, float] = {}

    for scene in script.scenes:
        narration_duration = audio_durations.get(
            scene.scene_id, estimate_narration_seconds(scene.narration)
        )
        # The storyboard builder must estimate from audio when available and add
        # 0.5s padding; enforce a 2.5s floor for very short lines.
        duration = max(2.5, narration_duration + SCENE_PADDING_SECONDS)
        duration = min(MAX_SCENE_SECONDS, duration)
        durations[scene.scene_id] = duration

    durations = _stretch_to_target(
        durations,
        minimum=pack.min_duration_seconds,
        maximum=pack.max_duration_seconds,
    )

    for scene in script.scenes:
        narration_duration = audio_durations.get(
            scene.scene_id, estimate_narration_seconds(scene.narration)
        )
        scenes.append(
            StoryboardScene(
                scene_id=scene.scene_id,
                layout=scene.layout,
                heading=(
                    script.title
                    if scene.layout == "title"
                    else LAYOUT_HEADINGS.get(scene.layout, scene.visual_description[:60])
                ),
                concept_title=script.title,
                concept_summary=script.summary,
                duration_seconds=durations[scene.scene_id],
                narration_text=scene.narration,
                caption_text=scene.narration,
                visual_description=scene.visual_description,
                palette=DEFAULT_PALETTE,
                elements=_elements(scene.layout, scene.on_screen_labels),
                animation="fade" if scene.layout == "title" else "fade_and_slide",
                transition_out="fade",
                narration_duration_seconds=round(narration_duration, 3),
                audio_path=audio_paths.get(scene.scene_id),
                is_placeholder_audio=placeholder_scene_ids.get(scene.scene_id, False),
            )
        )

    return Storyboard(
        concept_id=script.concept_id,
        title=script.title,
        summary=script.summary,
        script_source=script_source,
        content_version=pack.content_version,
        target_duration_seconds=script.target_duration_seconds,
        min_duration_seconds=pack.min_duration_seconds,
        max_duration_seconds=pack.max_duration_seconds,
        total_duration_seconds=round(sum(scene.duration_seconds for scene in scenes), 3),
        scenes=scenes,
    )


def estimate_script_durations(script: Script) -> dict[int, float]:
    return {scene.scene_id: estimate_scene_seconds(scene.narration) for scene in script.scenes}
