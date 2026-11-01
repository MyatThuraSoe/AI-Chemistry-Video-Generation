"""Deterministic script validation rules."""

from __future__ import annotations

from app.domain.script import ConceptPack, Script, ScriptScene
from app.generation.script_validator import validate_script


def _scene(scene_id: int, narration: str, *, labels: list[str] | None = None) -> ScriptScene:
    return ScriptScene(
        scene_id=scene_id,
        layout="recap_list" if scene_id % 2 else "title",
        narration=narration,
        visual_description="A simple diagram supports the narration.",
        on_screen_labels=labels or [f"step {scene_id}"],
    )


def _script(
    *,
    concept_id: str = "demo",
    title: str = "A demo lesson",
    summary: str = "Electrons are shared between atoms.",
    scenes: list[ScriptScene] | None = None,
) -> Script:
    return Script(
        concept_id=concept_id,
        title=title,
        summary=summary,
        target_duration_seconds=20,
        scenes=scenes
        or [
            _scene(1, "An atom shares electrons with another atom."),
            _scene(2, "The shared electrons help the atom become more stable."),
            _scene(3, "Each atom contributes one electron to the shared pair."),
            _scene(4, "This arrangement is called a covalent bond."),
        ],
    )


def _pack(
    *,
    required_terms: list[str] | None = None,
    min_duration: float = 0,
    max_duration: float = 100,
    concept_id: str = "demo",
) -> ConceptPack:
    return ConceptPack(
        concept_id=concept_id,
        aliases=[concept_id],
        required_terms=required_terms or ["atom", "electron", "bond"],
        min_duration_seconds=min_duration,
        max_duration_seconds=max_duration,
        script=_script(concept_id=concept_id),
    )


def test_valid_script_passes() -> None:
    result = validate_script(_script(), _pack())
    assert result.valid, result.errors
    assert result.errors == []
    assert result.word_count > 0


def test_missing_required_term_fails() -> None:
    script = _script(
        title="A demo lesson",
        summary="Particles are shared.",
        scenes=[
            _scene(1, "A particle shares electrons with another particle."),
            _scene(2, "The shared electrons help the particle become more stable."),
            _scene(3, "Each particle contributes one electron to the shared pair."),
            _scene(4, "This arrangement is called a covalent bond."),
        ],
    )
    result = validate_script(script, _pack(required_terms=["atom"]))
    assert not result.valid
    assert any("missing required term" in error.lower() for error in result.errors)


def test_empty_narration_fails() -> None:
    script = _script(
        scenes=[
            _scene(1, "An atom shares electrons."),
            _scene(2, ""),
            _scene(3, "An atom shares another electron."),
            _scene(4, "This is a bond."),
        ]
    )
    result = validate_script(script, _pack())
    assert not result.valid
    assert any("narration must not be empty" in error for error in result.errors)


def test_too_many_scenes_fails() -> None:
    scenes = [_scene(index, "An atom shares an electron.") for index in range(1, 12)]
    result = validate_script(_script(scenes=scenes), _pack())
    assert not result.valid
    assert any("4 to 10 scenes" in error for error in result.errors)


def test_concept_mismatch_fails() -> None:
    result = validate_script(_script(concept_id="other"), _pack(concept_id="demo"))
    assert not result.valid
    assert any("does not match resolved concept" in error for error in result.errors)


def test_unsafe_absolute_wording_fails() -> None:
    script = _script(
        scenes=[
            _scene(1, "An atom always shares electrons."),
            _scene(2, "The shared electrons help the atom become stable."),
            _scene(3, "Each atom contributes one electron."),
            _scene(4, "This arrangement is a bond."),
        ]
    )
    result = validate_script(script, _pack())
    assert not result.valid
    assert any("absolute" in error.lower() for error in result.errors)


def test_duration_outside_tolerance_fails() -> None:
    result = validate_script(_script(), _pack(min_duration=200, max_duration=300))
    assert not result.valid
    assert any("outside the accepted range" in error for error in result.errors)
