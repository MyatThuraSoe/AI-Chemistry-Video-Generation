"""Canonical content must always pass the same validation as generated content."""

from __future__ import annotations

import pytest

from app.generation.concept_registry import ConceptRegistry
from app.generation.content import load_concept_packs
from app.generation.script_validator import validate_script
from app.generation.storyboard_builder import build_storyboard

REQUIRED_CONCEPTS = ("ph-scale", "covalent-bonding", "ionic-vs-covalent")
REQUIRED_QUERIES = (
    "How does the pH scale work?",
    "Why do atoms form covalent bonds?",
    "What is the difference between ionic and covalent bonding?",
)


@pytest.fixture(scope="module")
def registry() -> ConceptRegistry:
    return ConceptRegistry(load_concept_packs())


@pytest.mark.parametrize("concept_id", REQUIRED_CONCEPTS)
def test_canonical_script_is_valid(registry: ConceptRegistry, concept_id: str) -> None:
    pack = registry.require(concept_id)
    result = validate_script(pack.script, pack)
    assert result.valid, result.errors


@pytest.mark.parametrize("query", REQUIRED_QUERIES)
def test_required_query_maps_to_expected_concept(
    registry: ConceptRegistry,
    query: str,
) -> None:
    assert registry.resolve(query).concept_id in REQUIRED_CONCEPTS


@pytest.mark.parametrize("concept_id", REQUIRED_CONCEPTS)
def test_storyboard_hits_target_duration(
    registry: ConceptRegistry,
    concept_id: str,
) -> None:
    pack = registry.require(concept_id)
    storyboard = build_storyboard(pack.script, pack)
    assert (
        pack.min_duration_seconds
        <= storyboard.total_duration_seconds
        <= (pack.max_duration_seconds)
    )
    assert all(scene.duration_seconds <= 20.0 for scene in storyboard.scenes)
    assert all(
        scene.duration_seconds >= scene.narration_duration_seconds for scene in storyboard.scenes
    )


def test_all_packs_have_unique_ids_and_aliases() -> None:
    packs = load_concept_packs()
    assert {pack.concept_id for pack in packs} == set(REQUIRED_CONCEPTS)
    # Constructing the registry already asserts there are no alias conflicts.
    ConceptRegistry(packs)
