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


class TestQuotedColonDefinitions:
    """Tests for the \u201cTerm\u201d: and "Term": patterns (smart-quote/straight-quote + colon)."""

    def test_smart_quote_colon_single(self) -> None:
        text = '\u201cApplicable Margin\u201d: the percentage set forth in the Pricing Grid.'
        defs = extract_definitions(text)
        assert len(defs) == 1
        assert defs[0].term == "Applicable Margin"
        assert defs[0].pattern_engine == "smart_quote"

    def test_straight_quote_colon_single(self) -> None:
        text = '"Applicable Margin": the percentage set forth in the Pricing Grid.'
        defs = extract_definitions(text)
        assert len(defs) == 1
        assert defs[0].term == "Applicable Margin"
        assert defs[0].pattern_engine == "quoted"

    def test_smart_quote_colon_multiple(self) -> None:
        text = (
            '\u201cBorrower\u201d: the entity identified as such in the preamble.\n\n'
            '\u201cLender\u201d: each financial institution listed on Schedule 1.\n\n'
            '\u201cAgent\u201d: JPMorgan Chase Bank, N.A.'
        )
        defs = extract_definitions(text)
        terms = {d.term for d in defs}
        assert "Borrower" in terms
        assert "Lender" in terms
        # "Agent" starts with a false-positive-guarded word — should still match
        # since _is_false_positive checks startswith("Article"/"Section"/etc.),
        # not "Agent".
        assert "Agent" in terms

    def test_smart_quote_colon_multiline_term(self) -> None:
        """Term name may span lines in EDGAR HTML-to-text output."""
        text = '\u201cSenior\nSecured Notes\u201d: the $490,000,000 in aggregate principal amount.'
        defs = extract_definitions(text)
        assert len(defs) == 1
        assert "Senior" in defs[0].term
        assert "Secured Notes" in defs[0].term

    def test_colon_def_start_offset(self) -> None:
        """Definition body should start after the colon, not include it."""
        text = '\u201cTerm\u201d: the definition body starts here.'
        defs = extract_definitions(text)
        assert len(defs) == 1
        assert "the definition body" in defs[0].definition_text
        # def_start is after the colon
        assert defs[0].def_start > defs[0].char_end

    def test_smart_quote_with_leading_space(self) -> None:
        """EDGAR HTML-to-text often produces space after opening smart quote."""
        text = '\u201c Applicable Margin \u201d: the percentage rate per annum.'
        defs = extract_definitions(text)
        assert len(defs) == 1
        assert defs[0].term == "Applicable Margin"

    def test_digit_starting_term(self) -> None:
        """Terms like '2023 Senior Secured Notes' start with a digit."""
        text = '\u201c 2023 Senior Secured Notes \u201d: the $490,000,000 in aggregate principal amount.'
        defs = extract_definitions(text)
        assert len(defs) == 1
        assert "2023 Senior Secured Notes" in defs[0].term

    def test_means_still_preferred_over_colon(self) -> None:
        """When both 'means' and ':' could match, dedup keeps highest confidence."""
        text = (
            '\u201cIndebtedness\u201d means any obligation for borrowed money.\n\n'
            '\u201cPermitted Liens\u201d: liens permitted under Section 7.01.'
        )
        defs = extract_definitions(text)
        terms = {d.term: d for d in defs}
        assert "Indebtedness" in terms
        assert "Permitted Liens" in terms
        # Both should be smart_quote engine
        assert terms["Indebtedness"].pattern_engine == "smart_quote"
        assert terms["Permitted Liens"].pattern_engine == "smart_quote"


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
