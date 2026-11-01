"""Content packs. New concepts are added here."""

from __future__ import annotations

from app.domain.script import ConceptPack
from app.generation.content.canonical_scripts import CANONICAL_PACKS


def load_concept_packs() -> tuple[ConceptPack, ...]:
    """Return every registered content pack.

    Keep this function as the single registration point so adding a STEM concept
    does not require touching the API, worker, or renderer.
    """
    return CANONICAL_PACKS
