"""Deterministic script validation.

Validation runs before any audio or video work. An LLM-produced script is never
rendered without passing the same checks as the curated canonical scripts.
"""

from __future__ import annotations

import re

from app.domain.errors import ScriptValidationError
from app.domain.script import ConceptPack, Script, ScriptValidationResult

WORDS_PER_SECOND = 2.6
SCENE_PADDING_SECONDS = 0.5
MAX_SCENES = 10
MIN_SCENES = 4
DEFAULT_MAX_SCENE_SECONDS = 20.0
DEFAULT_DURATION_TOLERANCE_RATIO = 0.25

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?", re.UNICODE)

_KNOWN_LAYOUTS = frozenset(
    {
        "title",
        "ph_scale_overview",
        "ph_regions",
        "hydrogen_ions",
        "log_scale",
        "examples_on_scale",
        "recap_list",
        "valence_electrons",
        "electron_sharing",
        "nonmetal_sharing",
        "h2_molecule",
        "shared_attraction",
        "ionic_transfer",
        "metal_nonmetal",
        "ionic_ions",
        "salt_example",
        "covalent_share",
        "molecule_example",
        "comparison_table",
    }
)

# Deliberately conservative. Curated content avoids absolutes and never gives
# laboratory instructions; the same guard applies to any future LLM output.
_UNSAFE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\balways\b", re.IGNORECASE), "Avoid absolute claims such as 'always'."),
    (re.compile(r"\bnever\b", re.IGNORECASE), "Avoid absolute claims such as 'never'."),
    (re.compile(r"\bguarantee(?:d|s)?\b", re.IGNORECASE), "Avoid guaranteed outcomes."),
    (
        re.compile(r"\b(?:drink|taste|smell|sniff|touch)\b", re.IGNORECASE),
        "Do not instruct learners to ingest or handle chemicals.",
    ),
    (re.compile(r"\bbleach\b", re.IGNORECASE), "Do not discuss mixing household chemicals."),
    (
        re.compile(r"\bexplod(?:e|es|ed|ing|sion)\b", re.IGNORECASE),
        "Do not describe dangerous reactions.",
    ),
    (
        re.compile(
            r"\b(?:mix|combine|pour)\b.{0,60}\b(?:acid|base|bleach|cleaner|chemical)s?\b",
            re.IGNORECASE,
        ),
        "Do not provide mixing or handling instructions.",
    ),
)


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def estimate_narration_seconds(text: str) -> float:
    """Estimate narration duration at 2.6 words per second."""
    return count_words(text) / WORDS_PER_SECOND


def estimate_scene_seconds(text: str) -> float:
    """Estimated scene duration including the mandated 0.5s padding."""
    return max(2.0, estimate_narration_seconds(text) + SCENE_PADDING_SECONDS)


def validate_script(
    script: Script,
    pack: ConceptPack,
    *,
    duration_tolerance_ratio: float = DEFAULT_DURATION_TOLERANCE_RATIO,
    max_scene_seconds: float = DEFAULT_MAX_SCENE_SECONDS,
) -> ScriptValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    scene_estimates: dict[int, float] = {}

    if script.concept_id != pack.concept_id:
        errors.append(
            f"Script concept_id '{script.concept_id}' does not match resolved concept "
            f"'{pack.concept_id}'."
        )

    if not script.title.strip():
        errors.append("Script title must not be empty.")
    if not script.summary.strip():
        errors.append("Script summary must not be empty.")

    if not (MIN_SCENES <= len(script.scenes) <= MAX_SCENES):
        errors.append(
            f"Script must contain {MIN_SCENES} to {MAX_SCENES} scenes; got {len(script.scenes)}."
        )

    scene_ids: set[int] = set()
    combined_parts: list[str] = [script.title, script.summary]
    total_words = 0

    for scene in script.scenes:
        if scene.scene_id in scene_ids:
            errors.append(f"Duplicate scene_id: {scene.scene_id}.")
        scene_ids.add(scene.scene_id)

        if not scene.narration.strip():
            errors.append(f"Scene {scene.scene_id} narration must not be empty.")
        if not scene.visual_description.strip():
            errors.append(f"Scene {scene.scene_id} visual_description must not be empty.")
        if not scene.on_screen_labels:
            errors.append(f"Scene {scene.scene_id} must have at least one on-screen label.")
        for label in scene.on_screen_labels:
            if not label.strip():
                errors.append(f"Scene {scene.scene_id} contains an empty on-screen label.")
        if len(scene.on_screen_labels) > 4:
            warnings.append(
                f"Scene {scene.scene_id} has {len(scene.on_screen_labels)} labels; "
                "consider simplifying for readability."
            )
        if scene.layout not in _KNOWN_LAYOUTS:
            warnings.append(
                f"Scene {scene.scene_id} uses unknown layout '{scene.layout}'; "
                "the generic fallback layout will be used."
            )

        word_count = count_words(scene.narration)
        total_words += word_count
        estimate = estimate_scene_seconds(scene.narration)
        scene_estimates[scene.scene_id] = round(estimate, 3)
        if estimate > max_scene_seconds:
            errors.append(
                f"Scene {scene.scene_id} is estimated at {estimate:.1f}s, "
                f"above the {max_scene_seconds:.0f}s maximum."
            )

        combined_parts.extend(
            [scene.narration, scene.visual_description, " ".join(scene.on_screen_labels)]
        )

    combined = " ".join(combined_parts).lower()
    for term in pack.required_terms:
        if term.lower() not in combined:
            errors.append(f"Script is missing required term: {term}.")

    for pattern, reason in _UNSAFE_PATTERNS:
        match = pattern.search(combined)
        if match:
            errors.append(
                f"Unsafe or absolute wording detected: {reason} (matched '{match.group(0)}')."
            )

    estimated_total = sum(scene_estimates.values())
    lower = pack.min_duration_seconds * (1 - duration_tolerance_ratio)
    upper = pack.max_duration_seconds * (1 + duration_tolerance_ratio)
    if not (lower <= estimated_total <= upper):
        errors.append(
            f"Estimated duration {estimated_total:.1f}s is outside the accepted "
            f"range for {pack.concept_id} ({lower:.1f}s to {upper:.1f}s)."
        )

    return ScriptValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        word_count=total_words,
        estimated_duration_seconds=round(estimated_total, 3),
        scene_estimates=scene_estimates,
    )


def require_valid_script(
    script: Script,
    pack: ConceptPack,
    *,
    duration_tolerance_ratio: float = DEFAULT_DURATION_TOLERANCE_RATIO,
    max_scene_seconds: float = DEFAULT_MAX_SCENE_SECONDS,
) -> ScriptValidationResult:
    result = validate_script(
        script,
        pack,
        duration_tolerance_ratio=duration_tolerance_ratio,
        max_scene_seconds=max_scene_seconds,
    )
    if not result.valid:
        raise ScriptValidationError(
            result.errors[0],
            details={"errors": result.errors, "warnings": result.warnings},
        )
    return result
