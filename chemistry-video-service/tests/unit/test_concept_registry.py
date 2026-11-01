"""Concept registry resolution and alias coverage."""

from __future__ import annotations

import pytest

from app.domain.errors import UnsupportedConceptError
from app.generation.concept_registry import ConceptRegistry
from app.generation.content import load_concept_packs

REQUIRED_QUERIES = {
    "How does the pH scale work?": "ph-scale",
    "Why do atoms form covalent bonds?": "covalent-bonding",
    "What is the difference between ionic and covalent bonding?": "ionic-vs-covalent",
}


@pytest.fixture(scope="module")
def registry() -> ConceptRegistry:
    return ConceptRegistry(load_concept_packs())


def test_resolve_ph_scale_query(registry: ConceptRegistry) -> None:
    pack = registry.resolve("How does the pH scale work?")
    assert pack.concept_id == "ph-scale"


def test_resolve_covalent_query(registry: ConceptRegistry) -> None:
    pack = registry.resolve("Why do atoms form covalent bonds?")
    assert pack.concept_id == "covalent-bonding"


def test_resolve_ionic_vs_covalent_query(registry: ConceptRegistry) -> None:
    pack = registry.resolve("What is the difference between ionic and covalent bonding?")
    assert pack.concept_id == "ionic-vs-covalent"


@pytest.mark.parametrize(("query", "concept_id"), REQUIRED_QUERIES.items())
def test_required_queries_resolve(
    registry: ConceptRegistry,
    query: str,
    concept_id: str,
) -> None:
    assert registry.resolve(query).concept_id == concept_id


def test_unknown_query_raises_unsupported_concept(registry: ConceptRegistry) -> None:
    with pytest.raises(UnsupportedConceptError) as captured:
        registry.resolve("Why is the sky blue?")
    assert captured.value.code == "UNSUPPORTED_CONCEPT"
    assert captured.value.http_status == 422
    assert captured.value.details is not None
    assert len(captured.value.details["supported_concepts"]) == 3


def test_all_declared_aliases_resolve(registry: ConceptRegistry) -> None:
    for pack in registry.packs:
        for alias in pack.aliases:
            assert registry.resolve(alias).concept_id == pack.concept_id
