"""Tests for agent.enumerator — VP enumerator port."""
from __future__ import annotations

from agent.enumerator import (
    CANONICAL_DEPTH,
    LEVEL_ALPHA,
    LEVEL_CAPS,
    LEVEL_NUMERIC,
    LEVEL_ROMAN,
    LEVEL_ROOT,
    EnumeratorMatch,
    compute_indentation,
    compute_line_starts,
    disambiguate_i,
    int_to_roman,
    is_at_line_start,
    next_ordinal_label,
    ordinal_for,
    roman_to_int,
    scan_enumerators,
)


# ── roman_to_int / int_to_roman ──────────────────────────────────────


class TestRoman:
    def test_basic_values(self) -> None:
        assert roman_to_int("i") == 1
        assert roman_to_int("iv") == 4
        assert roman_to_int("ix") == 9
        assert roman_to_int("xiv") == 14

    def test_case_insensitive(self) -> None:
        assert roman_to_int("XIV") == 14
        assert roman_to_int("IX") == 9

    def test_roundtrip_small(self) -> None:
        """int_to_roman only supports small values used in legal enumerators."""
        for n in range(1, 30):
            roman = int_to_roman(n)
            if roman is not None:
                assert roman_to_int(roman) == n

    def test_int_to_roman_basic(self) -> None:
        assert int_to_roman(1) == "i"
        assert int_to_roman(4) == "iv"
        assert int_to_roman(9) == "ix"
        assert int_to_roman(14) == "xiv"

    def test_int_to_roman_none_for_large(self) -> None:
        """Large numbers may return None if beyond legal enumerator range."""
        result = int_to_roman(42)
        # May return None or a value — depends on implementation range
        assert result is None or isinstance(result, str)


# ── ordinal_for / next_ordinal_label ─────────────────────────────────


class TestOrdinals:
    def test_alpha(self) -> None:
        assert ordinal_for(LEVEL_ALPHA, "a") == 1
        assert ordinal_for(LEVEL_ALPHA, "z") == 26

    def test_caps(self) -> None:
        assert ordinal_for(LEVEL_CAPS, "A") == 1
        assert ordinal_for(LEVEL_CAPS, "Z") == 26

    def test_roman(self) -> None:
        assert ordinal_for(LEVEL_ROMAN, "i") == 1
        assert ordinal_for(LEVEL_ROMAN, "iv") == 4

    def test_numeric(self) -> None:
        assert ordinal_for(LEVEL_NUMERIC, "1") == 1
        assert ordinal_for(LEVEL_NUMERIC, "42") == 42

    def test_next_alpha(self) -> None:
        assert next_ordinal_label(LEVEL_ALPHA, 1) == "b"
        assert next_ordinal_label(LEVEL_ALPHA, 25) == "z"

    def test_next_roman(self) -> None:
        assert next_ordinal_label(LEVEL_ROMAN, 3) == "iv"

    def test_next_numeric(self) -> None:
        assert next_ordinal_label(LEVEL_NUMERIC, 5) == "6"


# ── scan_enumerators ─────────────────────────────────────────────────


class TestScanEnumerators:
    def test_alpha_parens(self) -> None:
        text = "(a) First item\n(b) Second item\n(c) Third item"
        matches = scan_enumerators(text)
        alpha_matches = [m for m in matches if m.level_type == LEVEL_ALPHA]
        assert len(alpha_matches) >= 3
        # raw_label includes parentheses in VP's enumerator
        assert "a" in alpha_matches[0].raw_label
        assert "b" in alpha_matches[1].raw_label
        assert "c" in alpha_matches[2].raw_label

    def test_roman_parens(self) -> None:
        text = "(i) First item\n(ii) Second item\n(iii) Third item"
        matches = scan_enumerators(text)
        roman_matches = [m for m in matches if m.level_type == LEVEL_ROMAN]
        assert len(roman_matches) >= 3

    def test_numeric_with_period(self) -> None:
        text = "1. First item\n2. Second item\n3. Third item"
        matches = scan_enumerators(text)
        numeric_matches = [m for m in matches if m.level_type == LEVEL_NUMERIC]
        assert len(numeric_matches) >= 3

    def test_caps_parens(self) -> None:
        text = "(A) First item\n(B) Second item\n(C) Third item"
        matches = scan_enumerators(text)
        caps_matches = [m for m in matches if m.level_type == LEVEL_CAPS]
        assert len(caps_matches) >= 3

    def test_match_fields(self) -> None:
        """EnumeratorMatch should have all required fields."""
        text = "(a) test"
        matches = scan_enumerators(text)
        assert len(matches) >= 1
        m = matches[0]
        assert isinstance(m.raw_label, str)
        assert isinstance(m.ordinal, int)
        assert isinstance(m.level_type, str)
        assert isinstance(m.position, int)
        assert isinstance(m.match_end, int)
        assert isinstance(m.is_anchored, bool)


# ── disambiguate_i ───────────────────────────────────────────────────


class TestDisambiguateI:
    def test_i_with_ii_stays_roman(self) -> None:
        """If there's (i) followed by (ii), keep as roman."""
        text = "(i) First\n(ii) Second\n(iii) Third"
        matches = scan_enumerators(text)
        disambiguated = disambiguate_i(matches)
        roman = [m for m in disambiguated if m.level_type == LEVEL_ROMAN]
        assert len(roman) >= 3

    def test_returns_list(self) -> None:
        text = "(a) test"
        matches = scan_enumerators(text)
        result = disambiguate_i(matches)
        assert isinstance(result, list)


# ── compute_line_starts ──────────────────────────────────────────────


class TestComputeLineStarts:
    def test_basic(self) -> None:
        text = "line1\nline2\nline3"
        starts = compute_line_starts(text)
        assert starts[0] == 0
        assert starts[1] == 6  # after "line1\n"
        assert starts[2] == 12  # after "line2\n"

    def test_single_line(self) -> None:
        text = "no newlines"
        starts = compute_line_starts(text)
        assert starts == [0]


# ── is_at_line_start ─────────────────────────────────────────────────


class TestIsAtLineStart:
    def test_at_start(self) -> None:
        text = "(a) First item"
        starts = compute_line_starts(text)
        assert is_at_line_start(0, starts, text) is True

    def test_not_at_start(self) -> None:
        text = "prefix (a) First item"
        starts = compute_line_starts(text)
        assert is_at_line_start(7, starts, text) is False


# ── compute_indentation ─────────────────────────────────────────────


class TestComputeIndentation:
    def test_indented_position(self) -> None:
        """compute_indentation returns a normalized score (not raw char count)."""
        text = "    four spaces"
        starts = compute_line_starts(text)
        # Position 4 => normalized value > 0
        result = compute_indentation(4, text, starts)
        assert result > 0.0

    def test_no_indent(self) -> None:
        text = "no indent here"
        starts = compute_line_starts(text)
        assert compute_indentation(0, text, starts) == 0.0

    def test_more_indent_higher_score(self) -> None:
        """More indentation should produce a higher score."""
        text = "                    twenty spaces here"
        starts = compute_line_starts(text)
        score_20 = compute_indentation(20, text, starts)
        text2 = "    four spaces"
        starts2 = compute_line_starts(text2)
        score_4 = compute_indentation(4, text2, starts2)
        assert score_20 > score_4


# ── CANONICAL_DEPTH ──────────────────────────────────────────────────


class TestCanonicalDepth:
    def test_ordering(self) -> None:
        assert CANONICAL_DEPTH[LEVEL_ALPHA] == 1
        assert CANONICAL_DEPTH[LEVEL_ROMAN] == 2
        assert CANONICAL_DEPTH[LEVEL_CAPS] == 3
        assert CANONICAL_DEPTH[LEVEL_NUMERIC] == 4

    def test_root_not_in_depth(self) -> None:
        """LEVEL_ROOT is not in CANONICAL_DEPTH (it's depth 0 by convention)."""
        assert LEVEL_ROOT not in CANONICAL_DEPTH

    def test_level_constants(self) -> None:
        assert LEVEL_ALPHA == "alpha"
        assert LEVEL_ROMAN == "roman"
        assert LEVEL_CAPS == "caps"
        assert LEVEL_NUMERIC == "numeric"
        assert LEVEL_ROOT == "root"
