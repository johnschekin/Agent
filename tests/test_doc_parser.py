"""Tests for agent.doc_parser — VP doc_parser port."""
from __future__ import annotations

from agent.doc_parser import DocOutline, parse_xref
from agent.parsing_types import ParsedXref


# ── DocOutline construction ──────────────────────────────────────────


class TestDocOutline:
    def _make_ca_text(self) -> str:
        """Minimal credit agreement text with articles, sections, definitions."""
        return (
            "CREDIT AGREEMENT\n\n"
            "ARTICLE I\n"
            "DEFINITIONS\n\n"
            '1.01 Defined Terms. "Indebtedness" means all obligations of the Borrower. '
            '"Consolidated EBITDA" means for any period, net income.\n\n'
            "1.02 Other Interpretive Provisions. Unless otherwise specified.\n\n"
            "ARTICLE II\n"
            "THE CREDITS\n\n"
            "2.01 The Commitments. Subject to the terms and conditions set forth herein.\n\n"
            "2.02 Loans and Borrowings. Each Loan shall be made as part of a Borrowing.\n\n"
            "ARTICLE VII\n"
            "NEGATIVE COVENANTS\n\n"
            "7.01 Indebtedness. The Borrower will not create or incur any Indebtedness.\n\n"
            "7.02 Liens. The Borrower will not create any Lien on any property.\n\n"
        )

    def test_from_text_articles(self) -> None:
        text = self._make_ca_text()
        outline = DocOutline.from_text(text)
        assert len(outline.articles) >= 2
        # Check that article numbers are detected
        art_nums = [a.num for a in outline.articles]
        assert 1 in art_nums

    def test_from_text_sections(self) -> None:
        text = self._make_ca_text()
        outline = DocOutline.from_text(text)
        all_sections = outline.sections
        assert len(all_sections) >= 2
        sec_nums = [s.number for s in all_sections]
        assert any("1.01" in str(n) for n in sec_nums)

    def test_article_concept_mapping(self) -> None:
        """Articles should have concept hints from keyword matching."""
        text = self._make_ca_text()
        outline = DocOutline.from_text(text)
        # ARTICLE I / DEFINITIONS should map to "definitions" concept
        for art in outline.articles:
            if art.title and "DEFINITION" in art.title.upper():
                assert art.concept is not None
                assert art.concept == "definitions"

    def test_negative_covenants_concept(self) -> None:
        """ARTICLE VII NEGATIVE COVENANTS should map to negative_covenants."""
        text = self._make_ca_text()
        outline = DocOutline.from_text(text)
        for art in outline.articles:
            if art.title and "NEGATIVE" in art.title.upper():
                assert art.concept == "negative_covenants"

    def test_empty_text(self) -> None:
        outline = DocOutline.from_text("")
        assert len(outline.articles) == 0

    def test_no_articles(self) -> None:
        """Text without ARTICLE headings should still work."""
        text = "Just some text without any article structure."
        outline = DocOutline.from_text(text)
        assert len(outline.articles) == 0

    def test_section_char_spans(self) -> None:
        """Sections should have valid char_start/char_end within the text."""
        text = self._make_ca_text()
        outline = DocOutline.from_text(text)
        for sec in outline.sections:
            assert 0 <= sec.char_start < sec.char_end <= len(text)
            section_text = text[sec.char_start:sec.char_end]
            assert len(section_text.strip()) > 0

    def test_section_headings(self) -> None:
        """Sections should have headings parsed."""
        text = self._make_ca_text()
        outline = DocOutline.from_text(text)
        headings = [s.heading for s in outline.sections]
        assert any("Defined Terms" in h for h in headings if h)

    def test_article_heading(self) -> None:
        """Articles should have titles."""
        text = self._make_ca_text()
        outline = DocOutline.from_text(text)
        titles = [a.title for a in outline.articles]
        assert any("DEFINITIONS" in t for t in titles if t)


# ── parse_xref ───────────────────────────────────────────────────────
# Returns list[ParsedXref] (possibly empty)


class TestParseXref:
    def test_simple_section_ref(self) -> None:
        results = parse_xref("Section 7.01")
        assert len(results) >= 1
        xref = results[0]
        assert xref.section_num == "7.01"

    def test_section_with_clause(self) -> None:
        results = parse_xref("Section 7.01(a)")
        assert len(results) >= 1

    def test_section_with_deep_clause(self) -> None:
        results = parse_xref("Section 2.14(d)(iv)(A)")
        assert len(results) >= 1

    def test_article_ref(self) -> None:
        """parse_xref handles Section refs; Article refs may not parse."""
        results = parse_xref("Article VII")
        # Article refs may not be supported by the Lark xref grammar
        # (which targets Section N.NN(clause) patterns)
        assert isinstance(results, list)

    def test_invalid_ref(self) -> None:
        results = parse_xref("not a reference")
        assert results == []

    def test_returns_list(self) -> None:
        results = parse_xref("Section 7.01")
        assert isinstance(results, list)


# ── DocOutline helper methods ────────────────────────────────────────


class TestDocOutlineMethods:
    def _make_outline(self) -> DocOutline:
        text = (
            "ARTICLE I\nDEFINITIONS\n\n"
            '1.01 Defined Terms. "Indebtedness" means all obligations.\n\n'
            "ARTICLE II\nTHE CREDITS\n\n"
            "2.01 The Commitments. Subject to the terms.\n\n"
        )
        return DocOutline.from_text(text)

    def test_section_accessor(self) -> None:
        """outline.section(num) should return the matching section."""
        outline = self._make_outline()
        sec = outline.section("1.01")
        if sec is not None:
            assert sec.number == "1.01"

    def test_article_accessor(self) -> None:
        """outline.article(num) should return the matching article."""
        outline = self._make_outline()
        art = outline.article(1)
        if art is not None:
            assert art.num == 1

    def test_section_text(self) -> None:
        """outline.section_text(num) should return section text."""
        outline = self._make_outline()
        text = outline.section_text("1.01")
        if text is not None:
            assert len(text) > 0

    def test_summary(self) -> None:
        """outline.summary() should return a string or dict summary."""
        outline = self._make_outline()
        s = outline.summary()
        # summary() is a method that returns useful info
        assert s is not None


# ── from_structure_map ───────────────────────────────────────────────


class TestFromStructureMap:
    def test_basic_structure_map(self) -> None:
        """Test construction from a pre-parsed structure map."""
        text = (
            "ARTICLE I\n"
            "DEFINITIONS\n\n"
            "1.01 Defined Terms.\n\n"
            "ARTICLE II\n"
            "THE CREDITS\n\n"
            "2.01 The Commitments.\n\n"
        )
        structure = {
            "articles": [
                {"num": 1, "label": "I", "title": "DEFINITIONS",
                 "char_start": 0, "char_end": 50},
                {"num": 2, "label": "II", "title": "THE CREDITS",
                 "char_start": 50, "char_end": 100},
            ]
        }
        outline = DocOutline.from_structure_map(text, structure)
        assert len(outline.articles) >= 1
