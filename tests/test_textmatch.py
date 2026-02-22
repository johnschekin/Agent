"""Tests for agent.textmatch module."""
from agent.textmatch import (
    PhraseHit,
    heading_matches,
    keyword_density,
    score_in_range,
    section_dna_density,
)


class TestPhraseHit:
    def test_frozen(self) -> None:
        hit = PhraseHit(phrase="test", char_offset=10, tier=1)
        assert hit.phrase == "test"
        assert hit.char_offset == 10
        assert hit.tier == 1


class TestScoreInRange:
    def test_zero_density(self) -> None:
        assert score_in_range(0.25, 0.55, 0.0) == 0.25

    def test_full_density(self) -> None:
        assert score_in_range(0.25, 0.55, 1.0) == 0.55

    def test_mid_density(self) -> None:
        result = score_in_range(0.0, 1.0, 0.5)
        assert abs(result - 0.5) < 1e-9

    def test_clamps_above_one(self) -> None:
        assert score_in_range(0.0, 1.0, 2.0) == 1.0


class TestSectionDnaDensity:
    def test_no_phrases(self) -> None:
        density, hits = section_dna_density("some text", [], [])
        assert density == 0.0
        assert hits == []

    def test_tier1_weights_double(self) -> None:
        text = "the borrower shall maintain a leverage ratio"
        density, hits = section_dna_density(text, ["leverage ratio"], [])
        assert density > 0
        assert len(hits) == 1
        assert hits[0].tier == 1

    def test_tier2_hits(self) -> None:
        text = "the borrower shall incur indebtedness"
        density, hits = section_dna_density(text, [], ["indebtedness"])
        assert len(hits) == 1
        assert hits[0].tier == 2

    def test_combined_density(self) -> None:
        text = "maximum leverage ratio and consolidated ebitda shall not exceed threshold"
        t1 = ["leverage ratio", "consolidated ebitda"]
        t2 = ["threshold"]
        density, hits = section_dna_density(text.lower(), t1, t2)
        # 2 tier1 hits (weight 2 each = 4) + 1 tier2 hit (weight 1) = 5/6
        assert len(hits) == 3
        assert abs(density - 5.0 / 6.0) < 1e-9

    def test_full_density_cap(self) -> None:
        text = "a b c d e f g h"
        t1 = ["a", "b", "c"]  # 3 * 2 = 6 -> density 1.0
        density, _ = section_dna_density(text, t1, [])
        assert density == 1.0


class TestHeadingMatches:
    def test_exact_match(self) -> None:
        result = heading_matches("Indebtedness", ["Indebtedness"])
        assert result == "Indebtedness"

    def test_case_insensitive(self) -> None:
        result = heading_matches("LIMITATION ON INDEBTEDNESS", ["Limitation on Indebtedness"])
        assert result == "Limitation on Indebtedness"

    def test_substring_match(self) -> None:
        result = heading_matches("Section 7.01 — Indebtedness", ["Indebtedness"])
        assert result == "Indebtedness"

    def test_whitespace_collapse(self) -> None:
        result = heading_matches("In debt ed ness", ["Indebtedness"])
        assert result == "Indebtedness"

    def test_no_match(self) -> None:
        result = heading_matches("Liens", ["Indebtedness", "Restricted Payments"])
        assert result is None

    def test_case_sensitive(self) -> None:
        result = heading_matches("indebtedness", ["Indebtedness"], case_insensitive=False)
        assert result is None


class TestKeywordDensity:
    def test_empty_keywords(self) -> None:
        density, hits = keyword_density("some text", [])
        assert density == 0.0
        assert hits == []

    def test_all_found(self) -> None:
        text = "the borrower shall maintain a leverage ratio"
        density, hits = keyword_density(text, ["borrower", "leverage"])
        assert density == 1.0
        assert len(hits) == 2

    def test_partial(self) -> None:
        text = "the borrower shall"
        density, hits = keyword_density(text, ["borrower", "leverage"])
        assert density == 0.5
        assert len(hits) == 1

    def test_offsets_correct(self) -> None:
        text = "hello world"
        _, hits = keyword_density(text, ["world"])
        assert hits[0].char_offset == 6
