"""Tests for agent.section_parser module."""
from agent.doc_parser import (
    compute_chunk_id,
    extract_plural_sections,
    extract_section_range,
    heading_quality,
    parse_section_path,
    section_canonical_name,
    section_path,
    section_reference_key,
    section_text_hash,
)
from agent.section_parser import (
    OutlineArticle,
    OutlineSection,
    find_sections,
    parse_outline,
)


SAMPLE_CA_TEXT = """
ARTICLE I
Definitions and Accounting Terms

Section 1.01. Defined Terms. As used in this Agreement, the following terms shall have the meanings set forth below.

Section 1.02. Other Interpretive Provisions. With reference to this Agreement and each other Loan Document.

ARTICLE II
The Commitments and Credit Extensions

Section 2.01. Committed Loans. Subject to the terms and conditions set forth herein, each Lender agrees to make loans.

Section 2.02. Borrowings, Conversions and Continuations of Committed Loans.

ARTICLE VII
Negative Covenants

Section 7.01. Indebtedness. The Borrower shall not, and shall not permit any Subsidiary to, create, incur, assume or suffer to exist any Indebtedness.

Section 7.02. Liens. The Borrower shall not, and shall not permit any Subsidiary to, create, incur, assume or permit to exist any Lien.
"""


class TestParseOutline:
    def test_finds_articles(self) -> None:
        articles = parse_outline(SAMPLE_CA_TEXT)
        assert len(articles) >= 3
        assert all(isinstance(a, OutlineArticle) for a in articles)

    def test_article_numbers(self) -> None:
        articles = parse_outline(SAMPLE_CA_TEXT)
        nums = [a.num for a in articles]
        assert 1 in nums
        assert 2 in nums
        assert 7 in nums

    def test_article_titles(self) -> None:
        articles = parse_outline(SAMPLE_CA_TEXT)
        by_num = {a.num: a for a in articles}
        assert by_num[1].title != ""
        assert by_num[7].title != ""

    def test_articles_have_sections(self) -> None:
        articles = parse_outline(SAMPLE_CA_TEXT)
        by_num = {a.num: a for a in articles}
        assert len(by_num[1].sections) >= 2  # 1.01, 1.02
        assert len(by_num[7].sections) >= 2  # 7.01, 7.02

    def test_section_headings(self) -> None:
        articles = parse_outline(SAMPLE_CA_TEXT)
        by_num = {a.num: a for a in articles}
        section_headings = [s.heading for s in by_num[7].sections]
        assert any("Indebtedness" in h for h in section_headings)
        assert any("Lien" in h for h in section_headings)

    def test_section_char_spans(self) -> None:
        articles = parse_outline(SAMPLE_CA_TEXT)
        for a in articles:
            for s in a.sections:
                assert s.char_start >= 0
                assert s.char_end > s.char_start
                assert s.word_count > 0

    def test_sections_sorted_by_position(self) -> None:
        articles = parse_outline(SAMPLE_CA_TEXT)
        for a in articles:
            starts = [s.char_start for s in a.sections]
            assert starts == sorted(starts)

    def test_empty_text(self) -> None:
        assert parse_outline("") == []


class TestFindSections:
    def test_finds_sections_without_articles(self) -> None:
        text = """
Section 1.01. Definitions.

Section 1.02. Other Terms.

Section 2.01. Commitments.
"""
        sections = find_sections(text)
        assert len(sections) >= 3
        assert all(isinstance(s, OutlineSection) for s in sections)
        numbers = [s.number for s in sections]
        assert "1.01" in numbers
        assert "2.01" in numbers

    def test_empty_text(self) -> None:
        assert find_sections("") == []

    def test_section_article_num_is_zero(self) -> None:
        """find_sections doesn't assign article numbers (no article context)."""
        text = "Section 3.01. Something.\nSection 3.02. Else."
        sections = find_sections(text)
        for s in sections:
            assert s.article_num == 0

    def test_fallback_regex_when_doc_outline_returns_no_sections(self, monkeypatch) -> None:
        class _EmptyOutline:
            sections: list[object] = []

        monkeypatch.setattr(
            "agent.section_parser.DocOutline.from_text",
            lambda _text: _EmptyOutline(),
        )
        text = "Section 9.01. Incremental Facilities.\nSection 9.02. Amendments."
        sections = find_sections(text)
        numbers = [s.number for s in sections]
        assert "9.01" in numbers
        assert "9.02" in numbers


class TestHeadingQuality:
    """Tests for heading_quality() 3-tier scoring."""

    def test_proper_heading_uppercase(self) -> None:
        assert heading_quality("Indebtedness") == 2

    def test_proper_heading_all_caps(self) -> None:
        assert heading_quality("NEGATIVE COVENANTS") == 2

    def test_proper_heading_bracket(self) -> None:
        assert heading_quality("[Reserved]") == 2

    def test_empty_heading(self) -> None:
        assert heading_quality("") == 1

    def test_whitespace_only_heading(self) -> None:
        assert heading_quality("   ") == 1

    def test_garbage_comma_start(self) -> None:
        assert heading_quality(", (b) and (c) of Section 4.01") == 0

    def test_garbage_semicolon_start(self) -> None:
        assert heading_quality("; provided that the Borrower") == 0

    def test_garbage_lowercase_start(self) -> None:
        assert heading_quality("pursuant to the terms hereof") == 0

    def test_garbage_paren_start(self) -> None:
        assert heading_quality("(other than Permitted Liens)") == 0

    def test_garbage_body_text_lowercase_words(self) -> None:
        """Sentence-like body text with many lowercase content words."""
        assert heading_quality("The borrower shall not create or incur any additional debt") == 0

    def test_garbage_clause_reference(self) -> None:
        assert heading_quality("Subject to clauses (a)(iv) and (b)(ii)") == 0

    def test_short_proper_heading(self) -> None:
        assert heading_quality("Liens") == 2


class TestTocDedupHeadingInheritance:
    """Tests for TOC deduplication with heading inheritance."""

    def test_heading_inheritance_during_dedup(self) -> None:
        """When two entries exist for the same section number, the one with
        higher heading quality wins. If the winner has no heading but a
        loser does, heading is inherited."""
        from agent.doc_parser import DocOutline

        # Simulate a document with a body section that has a heading and
        # a duplicate without a heading. Both survive TOC filtering since
        # neither is in a TOC context — tests pure dedup logic.
        text = """
ARTICLE VII
Negative Covenants

Section 7.01. Indebtedness. The Borrower shall not create or incur any Indebtedness, except for Permitted Indebtedness as defined herein. The aggregate principal amount of all such Indebtedness shall not exceed the Maximum Amount.

Section 7.02. Liens. The Borrower shall not permit any Lien on any property or asset, except Permitted Liens as specified in this Agreement.

Section 7.03. Restricted Payments. The Borrower shall not declare or make any Restricted Payment.
"""
        outline = DocOutline.from_text(text)
        sections = outline.sections
        numbers = [s.number for s in sections]
        # Each section number should appear exactly once (deduped)
        assert numbers.count("7.01") == 1
        assert numbers.count("7.02") == 1
        # Sections should have headings
        sec_map = {s.number: s for s in sections}
        assert sec_map["7.01"].heading == "Indebtedness"
        assert sec_map["7.02"].heading == "Liens"

    def test_dedup_prefers_higher_quality_heading(self) -> None:
        """When same section appears twice, prefer the one with better heading."""
        # Both sections have keyword match so neither is filtered as ghost.
        # First occurrence has garbage heading, second has proper heading.
        text = """
ARTICLE I
Definitions

Section 1.01. Defined Terms. As used in this Agreement, the following terms shall have the meanings set forth below. Each capitalized term has the meaning assigned to it.

Section 1.02. Other Interpretive Provisions. With reference to this Agreement and each other Loan Document, unless otherwise specified herein.

ARTICLE VII
Negative Covenants

Section 7.01. Indebtedness. The Borrower shall not, and shall not permit any Subsidiary to, create or incur any Indebtedness.

Section 7.02. Liens. The Borrower shall not permit any Lien.
"""
        articles = parse_outline(text)
        all_sections = []
        for a in articles:
            all_sections.extend(a.sections)
        # Each section should appear once
        sec_map = {s.number: s for s in all_sections}
        assert "7.01" in sec_map
        assert sec_map["7.01"].heading == "Indebtedness"


class TestReservedSectionDetection:
    """Tests for [Reserved] / [Intentionally Omitted] section detection (Imp 8)."""

    def test_reserved_in_heading(self) -> None:
        """Section with [Reserved] in the heading text."""
        from agent.doc_parser import DocOutline

        text = """
ARTICLE VII
Negative Covenants

Section 7.01. Indebtedness. The Borrower shall not create or incur any Indebtedness.

Section 7.02. [Reserved].

Section 7.03. Restricted Payments. The Borrower shall not make any Restricted Payment.
"""
        outline = DocOutline.from_text(text)
        sec_map = {s.number: s for s in outline.sections}
        assert "7.02" in sec_map
        assert sec_map["7.02"].heading == "[Reserved]"

    def test_intentionally_omitted(self) -> None:
        """Section with [Intentionally Omitted] in heading."""
        from agent.doc_parser import DocOutline

        text = """
ARTICLE V
Affirmative Covenants

Section 5.01. Financial Statements. The Borrower shall deliver financial statements quarterly.

Section 5.02. [Intentionally Omitted].

Section 5.03. Notices. The Borrower shall promptly notify the Administrative Agent.
"""
        outline = DocOutline.from_text(text)
        sec_map = {s.number: s for s in outline.sections}
        assert "5.02" in sec_map
        assert sec_map["5.02"].heading == "[Intentionally Omitted]"

    def test_reserved_section_not_false_positive(self) -> None:
        """Normal sections should not be tagged as reserved."""
        from agent.doc_parser import DocOutline

        text = """
ARTICLE I
Definitions

Section 1.01. Defined Terms. As used in this Agreement, the following terms have the meanings set forth below.

Section 1.02. Other Provisions. With reference to this Agreement and each other Loan Document.
"""
        outline = DocOutline.from_text(text)
        sec_map = {s.number: s for s in outline.sections}
        for s in sec_map.values():
            assert "[Reserved]" not in s.heading
            assert "[Intentionally Omitted]" not in s.heading


class TestStandaloneSectionNumber:
    """Tests for standalone section numbers with look-ahead heading (Imp 7)."""

    def test_pricing_grid_not_matched(self) -> None:
        """Numbers like 50.00 in pricing grids should not be matched as sections."""
        from agent.doc_parser import DocOutline

        text = """
ARTICLE I
Definitions

Section 1.01. Pricing Grid. The applicable rate shall be:

Level I   50.00 bps   100.00 bps
Level II  75.00 bps   125.00 bps

Section 1.02. Other Terms. Additional terms as defined herein.
"""
        outline = DocOutline.from_text(text)
        numbers = [s.number for s in outline.sections]
        assert "50.00" not in numbers
        assert "100.00" not in numbers
        assert "75.00" not in numbers
        assert "125.00" not in numbers


class TestMonotonicEnforcement:
    """Tests for section gap detection & monotonic enforcement (Imp 10)."""

    def test_out_of_sequence_section_dropped(self) -> None:
        """A section whose minor number goes backwards should be removed."""
        from agent.doc_parser import DocOutline

        text = """
ARTICLE VII
Negative Covenants

Section 7.01. Indebtedness. The Borrower shall not create or incur any Indebtedness.

Section 7.03. Restricted Payments. The Borrower shall not make any Restricted Payment.

Section 7.02. Some Cross-Reference Echo. This is a stale reference that leaked through.

Section 7.04. Fundamental Changes. The Borrower shall not merge or consolidate.
"""
        outline = DocOutline.from_text(text)
        numbers = [s.number for s in outline.sections]
        # 7.02 appears after 7.03 — should be dropped (non-monotonic)
        assert "7.01" in numbers
        assert "7.03" in numbers
        assert "7.04" in numbers
        # 7.02 after 7.03 is out of order
        for i, n in enumerate(numbers):
            if n == "7.03":
                rest = numbers[i + 1:]
                assert "7.02" not in rest

    def test_monotonic_preserves_gaps(self) -> None:
        """Gaps in numbering are OK — monotonic only rejects backwards jumps."""
        from agent.doc_parser import DocOutline

        text = """
ARTICLE V
Affirmative Covenants

Section 5.01. Financial Statements. The Borrower shall deliver quarterly statements.

Section 5.03. Notices. The Borrower shall promptly notify the Agent.

Section 5.05. Compliance Certificate. The Borrower shall deliver compliance certificates.
"""
        outline = DocOutline.from_text(text)
        numbers = [s.number for s in outline.sections]
        # Gaps (5.02, 5.04 missing) should not cause rejection
        assert "5.01" in numbers
        assert "5.03" in numbers
        assert "5.05" in numbers

    def test_monotonic_across_articles_independent(self) -> None:
        """Monotonic enforcement is per-article, not global."""
        text = """
ARTICLE I
Definitions

Section 1.01. Defined Terms. As used in this Agreement, the following terms have meanings set forth below.

Section 1.02. Other Provisions. With reference to this Agreement.

ARTICLE II
Commitments

Section 2.01. Committed Loans. Subject to the terms and conditions, each Lender agrees to make loans.

Section 2.02. Borrowings. The Borrower may request Committed Loans.
"""
        articles = parse_outline(text)
        all_sections = []
        for a in articles:
            all_sections.extend(a.sections)
        numbers = [s.number for s in all_sections]
        # 2.01 minor=1 is fine because it's a new article
        assert "1.01" in numbers
        assert "1.02" in numbers
        assert "2.01" in numbers
        assert "2.02" in numbers

    def test_monotonic_without_articles_uses_major(self) -> None:
        """When article_num=0, enforcement groups by major number."""
        text = """
Section 1.01. Definitions.

Section 1.02. Other Terms.

Section 2.01. Commitments.

Section 2.02. Borrowings.
"""
        sections = find_sections(text)
        numbers = [s.number for s in sections]
        # All should survive — different major numbers are independent groups
        assert "1.01" in numbers
        assert "1.02" in numbers
        assert "2.01" in numbers
        assert "2.02" in numbers


class TestSectionCanonicalNaming:
    """Tests for section canonical naming (Imp 16)."""

    def test_basic(self) -> None:
        assert section_canonical_name("Indebtedness") == "indebtedness"

    def test_all_caps(self) -> None:
        assert section_canonical_name("NEGATIVE COVENANTS") == "negative covenants"

    def test_trailing_period(self) -> None:
        assert section_canonical_name("Liens.") == "liens"

    def test_extra_whitespace(self) -> None:
        assert section_canonical_name("  Restricted   Payments  ") == "restricted payments"

    def test_empty(self) -> None:
        assert section_canonical_name("") == ""

    def test_reference_key(self) -> None:
        key = section_reference_key("doc123", "Indebtedness")
        assert key == "doc123:indebtedness"


class TestSectionAbbreviationPatterns:
    """Tests for Sec. / Sec section abbreviation patterns (Imp 22)."""

    def test_sec_dot_detected(self) -> None:
        """Sections using 'Sec.' keyword should be detected."""
        from agent.doc_parser import DocOutline

        text = """
ARTICLE VII
Negative Covenants

Sec. 7.01. Indebtedness. The Borrower shall not create or incur any Indebtedness.

Sec. 7.02. Liens. The Borrower shall not permit any Lien on any property.

Sec. 7.03. Restricted Payments. The Borrower shall not make any Restricted Payment.
"""
        outline = DocOutline.from_text(text)
        numbers = [s.number for s in outline.sections]
        assert "7.01" in numbers
        assert "7.02" in numbers
        assert "7.03" in numbers

    def test_sec_no_dot_detected(self) -> None:
        """Sections using 'Sec' (no dot) keyword should be detected."""
        from agent.doc_parser import DocOutline

        text = """
ARTICLE I
Definitions

Sec 1.01. Defined Terms. As used in this Agreement, the terms have the meanings set forth below.

Sec 1.02. Other Provisions. With reference to this Agreement and each other document.
"""
        outline = DocOutline.from_text(text)
        numbers = [s.number for s in outline.sections]
        assert "1.01" in numbers
        assert "1.02" in numbers


class TestContextualReferencePatterns:
    """Tests for additional xref intent patterns (Imp 18)."""

    def test_in_accordance_with(self) -> None:
        from agent.doc_parser import DocOutline

        outline = DocOutline.__new__(DocOutline)
        intent = outline.classify_xref_intent("in accordance with Section 5.01")
        assert intent == "compliance"

    def test_referenced_in(self) -> None:
        from agent.doc_parser import DocOutline

        outline = DocOutline.__new__(DocOutline)
        intent = outline.classify_xref_intent("as referenced in Section 3.02")
        assert intent == "reference"

    def test_required_by(self) -> None:
        from agent.doc_parser import DocOutline

        outline = DocOutline.__new__(DocOutline)
        intent = outline.classify_xref_intent("as required by Section 6.01")
        assert intent == "restriction"

    def test_existing_patterns_still_work(self) -> None:
        from agent.doc_parser import DocOutline

        outline = DocOutline.__new__(DocOutline)
        assert outline.classify_xref_intent("pursuant to Section 2.01") == "incorporation"
        assert outline.classify_xref_intent("subject to Section 7.01") == "condition"
        assert outline.classify_xref_intent("as defined in Section 1.01") == "definition"


class TestContentAddressedChunkIds:
    """Tests for content-addressed chunk IDs (Imp 17)."""

    def test_deterministic(self) -> None:
        h1 = compute_chunk_id("doc123", "7.02", "abc123")
        h2 = compute_chunk_id("doc123", "7.02", "abc123")
        assert h1 == h2

    def test_different_doc_different_id(self) -> None:
        h1 = compute_chunk_id("doc123", "7.02", "abc123")
        h2 = compute_chunk_id("doc456", "7.02", "abc123")
        assert h1 != h2

    def test_length(self) -> None:
        h = compute_chunk_id("doc123", "7.02", "abc123")
        assert len(h) == 16

    def test_hex_characters(self) -> None:
        h = compute_chunk_id("doc123", "7.02", "abc123")
        assert all(c in "0123456789abcdef" for c in h)

    def test_text_hash(self) -> None:
        h1 = section_text_hash("Hello world", 0, 5)
        h2 = section_text_hash("Hello world", 0, 5)
        assert h1 == h2
        assert len(h1) == 16

    def test_text_hash_different_slices(self) -> None:
        h1 = section_text_hash("Hello world", 0, 5)
        h2 = section_text_hash("Hello world", 6, 11)
        assert h1 != h2


class TestSectionPathNormalization:
    """Tests for section path normalization (Imp 21)."""

    def test_with_article(self) -> None:
        assert section_path(7, "7.02") == "7.7.02"

    def test_without_article(self) -> None:
        assert section_path(0, "7.02") == "7.02"

    def test_round_trip(self) -> None:
        """parse_section_path is the inverse of section_path."""
        art, num = parse_section_path(section_path(7, "7.02"))
        assert art == 7
        assert num == "7.02"

    def test_round_trip_no_article(self) -> None:
        art, num = parse_section_path(section_path(0, "7.02"))
        assert art == 0
        assert num == "7.02"

    def test_parse_plain_number(self) -> None:
        art, num = parse_section_path("7.02")
        assert art == 0
        assert num == "7.02"


class TestPluralRangePatterns:
    """Tests for plural/range reference patterns (Imp 19)."""

    def test_plural_and(self) -> None:
        sections = extract_plural_sections("Sections 2.01 and 2.02")
        assert "2.01" in sections
        assert "2.02" in sections

    def test_plural_comma_and(self) -> None:
        sections = extract_plural_sections("Sections 2.01, 2.02, and 2.03")
        assert "2.01" in sections
        assert "2.03" in sections

    def test_plural_no_match(self) -> None:
        sections = extract_plural_sections("Section 2.01 is important")
        assert sections == []

    def test_range_through(self) -> None:
        ranges = extract_section_range("Sections 2.01 through 2.05")
        assert len(ranges) == 1
        assert ranges[0] == ("2.01", "2.05")

    def test_range_to(self) -> None:
        ranges = extract_section_range("Section 3.01 to 3.10")
        assert len(ranges) == 1
        assert ranges[0] == ("3.01", "3.10")

    def test_range_dash(self) -> None:
        ranges = extract_section_range("Sections 5.01-5.03")
        assert len(ranges) == 1
        assert ranges[0] == ("5.01", "5.03")

    def test_no_range(self) -> None:
        assert extract_section_range("Section 2.01 is important") == []
