"""Query normalization rules from the specification."""

from __future__ import annotations

from app.generation.concept_registry import normalize_query


def test_normalize_query_removes_punctuation() -> None:
    assert normalize_query("How does the pH scale work?!") == "how does the ph scale work"
    assert normalize_query("What is H2O's shape?") == "what is h2o s shape"


def test_normalize_query_lowercases_text() -> None:
    assert normalize_query("WHY Do ATOMS Form Covalent Bonds?") == (
        "why do atoms form covalent bonds"
    )


def test_normalize_query_collapses_whitespace() -> None:
    assert normalize_query("  How   does\t the \n pH scale work?  ") == (
        "how does the ph scale work"
    )
