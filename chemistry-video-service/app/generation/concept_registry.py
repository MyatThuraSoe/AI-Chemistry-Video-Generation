"""Query normalization and concept resolution."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.domain.errors import UnsupportedConceptError
from app.domain.script import ConceptPack

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_query(query: str) -> str:
    """Normalize a learner query for alias matching.

    Trims, lowercases, replaces punctuation (including the trailing question
    mark) with spaces, and collapses whitespace.
    """
    normalized = _NON_WORD.sub(" ", query)
    normalized = normalized.lower()
    return _WHITESPACE.sub(" ", normalized).strip()


class ConceptRegistry:
    def __init__(self, packs: Iterable[ConceptPack]) -> None:
        self._packs: dict[str, ConceptPack] = {}
        self._aliases: dict[str, str] = {}
        for pack in packs:
            if pack.concept_id in self._packs:
                raise ValueError(f"Duplicate concept_id: {pack.concept_id}")
            self._packs[pack.concept_id] = pack
            for alias in pack.aliases:
                normalized_alias = normalize_query(alias)
                if not normalized_alias:
                    raise ValueError(f"Empty alias in concept {pack.concept_id}")
                existing = self._aliases.get(normalized_alias)
                if existing is not None and existing != pack.concept_id:
                    raise ValueError(
                        f"Alias {alias!r} is registered for both {existing} and {pack.concept_id}"
                    )
                self._aliases[normalized_alias] = pack.concept_id

    @property
    def packs(self) -> tuple[ConceptPack, ...]:
        return tuple(self._packs.values())

    def get(self, concept_id: str) -> ConceptPack | None:
        return self._packs.get(concept_id)

    def require(self, concept_id: str) -> ConceptPack:
        pack = self.get(concept_id)
        if pack is None:
            raise KeyError(f"Unknown concept_id: {concept_id}")
        return pack

    def resolve(self, query: str) -> ConceptPack:
        normalized = normalize_query(query)
        concept_id = self._aliases.get(normalized)
        if concept_id is None:
            raise UnsupportedConceptError(query)
        return self._packs[concept_id]

    def resolve_normalized(self, normalized_query: str) -> ConceptPack:
        concept_id = self._aliases.get(normalized_query)
        if concept_id is None:
            raise UnsupportedConceptError(normalized_query)
        return self._packs[concept_id]

    def register(self, pack: ConceptPack) -> None:
        if pack.concept_id in self._packs:
            raise ValueError(f"concept_id already registered: {pack.concept_id}")
        for alias in pack.aliases:
            normalized_alias = normalize_query(alias)
            if normalized_alias in self._aliases:
                raise ValueError(f"Alias already registered: {alias!r}")
        self._packs[pack.concept_id] = pack
        for alias in pack.aliases:
            self._aliases[normalize_query(alias)] = pack.concept_id
