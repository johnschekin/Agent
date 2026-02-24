"""Tests for agent.dna module."""
from __future__ import annotations

from agent.dna import discover_dna_phrases


class TestDnaDiscovery:
    def test_discovers_distinctive_phrase(self) -> None:
        positives = [
            "The Borrower may incur ratio debt if leverage ratio test is satisfied.",
            "Ratio debt basket permits indebtedness based on leverage ratio.",
            "Additional ratio debt is permitted under leverage ratio covenant.",
        ]
        backgrounds = [
            "The Borrower shall deliver quarterly financial statements.",
            "Administrative Agent may request compliance certificates.",
            "Representations and warranties survive until closing.",
        ]
        out = discover_dna_phrases(positives, backgrounds, top_k=20)
        assert out, "Expected non-empty DNA candidates"
        phrases = [c.phrase for c in out]
        assert any("ratio debt" in p for p in phrases)

    def test_filters_phrase_with_high_background_rate(self) -> None:
        positives = [
            "indebtedness indebtedness ratio debt",
            "indebtedness leverage ratio debt",
        ]
        backgrounds = [
            "indebtedness appears everywhere",
            "indebtedness also appears here",
        ]
        out = discover_dna_phrases(
            positives,
            backgrounds,
            max_bg_rate=0.0,
            min_section_rate=0.5,
            top_k=30,
        )
        phrases = [c.phrase for c in out]
        assert "indebtedness" not in phrases

    def test_empty_positive_returns_empty(self) -> None:
        out = discover_dna_phrases([], ["background only"])
        assert out == []

