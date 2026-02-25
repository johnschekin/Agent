"""Tests for compile_section_map.py — HHI stability and section map building."""
from collections import Counter

from scripts.compile_section_map import (
    build_section_map,
    compute_hhi,
    location_strategy,
)


class TestComputeHHI:
    """Tests for HHI stability computation."""

    def test_perfect_concentration(self) -> None:
        """All hits in one section → HHI = 1.0."""
        counts: Counter[str] = Counter({"7.01": 10})
        assert compute_hhi(counts) == 1.0

    def test_uniform_distribution(self) -> None:
        """Equal hits across sections → HHI near 0.0."""
        counts: Counter[str] = Counter({"7.01": 10, "7.02": 10, "7.03": 10, "7.04": 10})
        hhi = compute_hhi(counts)
        assert hhi < 0.05

    def test_moderate_concentration(self) -> None:
        """Skewed but not perfect → HHI between 0 and 1."""
        counts: Counter[str] = Counter({"7.01": 8, "7.02": 1, "7.03": 1})
        hhi = compute_hhi(counts)
        assert 0.3 < hhi < 1.0

    def test_empty_counts(self) -> None:
        """No data → 0.5 (insufficient data)."""
        assert compute_hhi(Counter()) == 0.5

    def test_two_sections_equal(self) -> None:
        """Two sections with equal counts → HHI = 0.0."""
        counts: Counter[str] = Counter({"7.01": 5, "7.02": 5})
        assert compute_hhi(counts) == 0.0


class TestLocationStrategy:
    def test_high_stability(self) -> None:
        assert location_strategy(0.8) == "adjacent_sections"

    def test_medium_stability(self) -> None:
        assert location_strategy(0.5) == "same_article"

    def test_low_stability(self) -> None:
        assert location_strategy(0.1) == "full_article_scan"

    def test_boundary_high(self) -> None:
        assert location_strategy(0.7) == "adjacent_sections"

    def test_boundary_medium(self) -> None:
        assert location_strategy(0.3) == "same_article"


class TestBuildSectionMap:
    def test_basic_build(self) -> None:
        evidence = {
            "test_concept": {
                "sections": Counter({"7.01": 5, "7.02": 2}),
                "articles": Counter({"7": 7}),
                "headings": ["Indebtedness"],
                "n_strategies": 1,
                "best_score": 0.85,
            },
        }
        result = build_section_map(evidence, {})
        assert len(result) == 1
        entry = result[0]
        assert entry["concept_id"] == "test_concept"
        assert entry["stability_score"] > 0
        assert entry["location_strategy"] in ("adjacent_sections", "same_article", "full_article_scan")
        assert len(entry["top_sections"]) > 0
        assert entry["headings"] == ["Indebtedness"]

    def test_corpus_enrichment(self) -> None:
        """Corpus prevalence should enrich section counts."""
        evidence = {
            "test_concept": {
                "sections": Counter({"7.01": 1}),
                "articles": Counter(),
                "headings": ["Indebtedness"],
                "n_strategies": 1,
                "best_score": 0.5,
            },
        }
        corpus = {
            "indebtedness": Counter({"7.01": 50, "7.03": 10}),
        }
        result = build_section_map(evidence, corpus)
        entry = result[0]
        # Corpus data should inflate the counts
        assert entry["total_section_hits"] > 1
