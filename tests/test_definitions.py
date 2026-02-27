"""Tests for agent.definitions module."""
from agent.definitions import (
    DefinedTerm,
    extract_definitions,
    extract_term_references,
    find_term,
)


SAMPLE_DEFINITIONS_TEXT = '''
"Indebtedness" means any obligation for borrowed money, including without limitation any obligation evidenced by bonds, debentures, notes or similar instruments.

"Consolidated EBITDA" shall mean, for any period, the Consolidated Net Income for such period.

"Permitted Indebtedness" means Indebtedness permitted under Section 7.01.
'''


class TestExtractDefinitions:
    def test_finds_quoted_definitions(self) -> None:
        defs = extract_definitions(SAMPLE_DEFINITIONS_TEXT)
        terms = [d.term for d in defs]
        assert "Indebtedness" in terms
        assert "Consolidated EBITDA" in terms

    def test_definition_attributes(self) -> None:
        defs = extract_definitions(SAMPLE_DEFINITIONS_TEXT)
        assert all(isinstance(d, DefinedTerm) for d in defs)
        for d in defs:
            assert d.char_start >= 0
            assert d.char_end > d.char_start
            assert 0.0 <= d.confidence <= 1.0
            assert d.pattern_engine in ("quoted", "smart_quote", "parenthetical", "colon", "unquoted")

    def test_sorted_by_position(self) -> None:
        defs = extract_definitions(SAMPLE_DEFINITIONS_TEXT)
        starts = [d.char_start for d in defs]
        assert starts == sorted(starts)

    def test_deduplication(self) -> None:
        # "Indebtedness" appears in both definition and "Permitted Indebtedness"
        defs = extract_definitions(SAMPLE_DEFINITIONS_TEXT)
        term_names = [d.term for d in defs]
        # Each term should appear only once
        assert len(term_names) == len(set(t.lower() for t in term_names))

    def test_global_offset(self) -> None:
        defs_no_offset = extract_definitions(SAMPLE_DEFINITIONS_TEXT)
        defs_with_offset = extract_definitions(SAMPLE_DEFINITIONS_TEXT, global_offset=500)
        if defs_no_offset and defs_with_offset:
            assert defs_with_offset[0].char_start == defs_no_offset[0].char_start + 500

    def test_long_definition_not_truncated_at_2000_chars(self) -> None:
        long_body = " ".join(["cash flow adjustment"] * 180) + ".\n\n"
        text = (
            f'"Long Definition Term" means {long_body}'
            '"Short Term" means a shorter body.'
        )
        defs = extract_definitions(text)
        long_def = next(d for d in defs if d.term == "Long Definition Term")
        assert len(long_def.definition_text) > 2000


class TestFindTerm:
    def test_find_existing_term(self) -> None:
        result = find_term(SAMPLE_DEFINITIONS_TEXT, "Indebtedness")
        assert result is not None
        assert result.term == "Indebtedness"

    def test_find_nonexistent_term(self) -> None:
        result = find_term(SAMPLE_DEFINITIONS_TEXT, "Nonexistent Term")
        assert result is None


SMART_QUOTE_TEXT = '\u201cIndebtedness\u201d means any obligation for borrowed money.'


class TestSmartQuotes:
    def test_smart_quote_detection(self) -> None:
        defs = extract_definitions(SMART_QUOTE_TEXT)
        terms = [d.term for d in defs]
        assert "Indebtedness" in terms


class TestExtractTermReferences:
    def test_finds_references(self) -> None:
        text = "The Borrower shall not incur any Indebtedness or create any Liens."
        refs = extract_term_references(text, ["Indebtedness", "Liens", "Borrower"])
        terms_found = [r[0] for r in refs]
        assert "Indebtedness" in terms_found
        assert "Liens" in terms_found

    def test_returns_offsets(self) -> None:
        text = "The Borrower and the Indebtedness."
        refs = extract_term_references(text, ["Borrower", "Indebtedness"])
        for term, offset in refs:
            assert text[offset:offset + len(term)] == term
