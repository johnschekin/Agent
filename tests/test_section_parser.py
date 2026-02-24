"""Tests for agent.section_parser module."""
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
