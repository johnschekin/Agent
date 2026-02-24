"""Tests for Block-1.1 zero-section recovery fixes in doc_parser.

Each test constructs synthetic text that exercises a specific failure mode
(Fix A-E) and verifies that DocOutline.from_text() now recovers sections.
"""
from __future__ import annotations

from agent.doc_parser import (
    DocOutline,
    _is_toc_entry,  # type: ignore[attr-defined]  # noqa: E402
)

# ── Fix A: Part/Chapter/Clause article patterns ──────────────────────


class TestPartBasedArticles:
    """Documents using 'Part I / Part II' instead of 'ARTICLE I'."""

    def _make_part_text(self) -> str:
        return (
            "CREDIT AGREEMENT\n\n"
            "Part I\n"
            "DEFINITIONS\n\n"
            "Section 1.01 Defined Terms. The following terms have the meanings assigned:\n"
            '"Borrower" means the Company.\n'
            '"Agent" means the Administrative Agent.\n\n'
            "Section 1.02 Other Terms. Terms used herein shall have the meanings.\n\n"
            "Part II\n"
            "THE CREDITS\n\n"
            "Section 2.01 Commitments. Subject to the terms herein, each Lender agrees.\n\n"
            "Section 2.02 Loans. Each Loan shall be made as part of a Borrowing.\n\n"
            "Part III\n"
            "NEGATIVE COVENANTS\n\n"
            "Section 3.01 Indebtedness. The Borrower will not incur any Indebtedness.\n\n"
            "Section 3.02 Liens. The Borrower will not create any Lien.\n\n"
        )

    def test_finds_articles(self) -> None:
        text = self._make_part_text()
        outline = DocOutline.from_text(text)
        assert len(outline.articles) >= 2, (
            f"Expected >= 2 articles from Part-based doc, got {len(outline.articles)}"
        )

    def test_finds_sections(self) -> None:
        text = self._make_part_text()
        outline = DocOutline.from_text(text)
        assert len(outline.sections) >= 4, (
            f"Expected >= 4 sections, got {len(outline.sections)}"
        )
        sec_nums = {s.number for s in outline.sections}
        assert "1.01" in sec_nums or any("1.01" in n for n in sec_nums)


class TestChapterBasedArticles:
    """Documents using 'Chapter 1' instead of 'ARTICLE I'."""

    def _make_chapter_text(self) -> str:
        return (
            "CREDIT AGREEMENT\n\n"
            "Chapter 1\n"
            "DEFINITIONS AND INTERPRETATION\n\n"
            "Section 1.01 Defined Terms. As used in this Agreement.\n\n"
            "Section 1.02 Accounting Terms. All accounting terms.\n\n"
            "Chapter 2\n"
            "THE FACILITY\n\n"
            "Section 2.01 Commitments. Each Lender hereby agrees to make Loans.\n\n"
            "Section 2.02 Borrowing Procedures. The Borrower shall give notice.\n\n"
            "Chapter 3\n"
            "CONDITIONS PRECEDENT\n\n"
            "Section 3.01 Conditions to Effectiveness. This Agreement shall become effective.\n\n"
        )

    def test_finds_articles(self) -> None:
        text = self._make_chapter_text()
        outline = DocOutline.from_text(text)
        assert len(outline.articles) >= 2

    def test_finds_sections(self) -> None:
        text = self._make_chapter_text()
        outline = DocOutline.from_text(text)
        assert len(outline.sections) >= 3


class TestClauseBasedArticles:
    """Documents using top-level 'Clause N' divisions."""

    def _make_clause_text(self) -> str:
        return (
            "FACILITY AGREEMENT\n\n"
            "Clause 1\n"
            "DEFINITIONS AND INTERPRETATION\n\n"
            "Section 1.01 Defined Terms. In this Agreement the following terms.\n\n"
            "Section 1.02 Interpretation. References to Clauses are references.\n\n"
            "Clause 2\n"
            "THE FACILITY\n\n"
            "Section 2.01 The Facility. The Lenders make available a term loan facility.\n\n"
            "Clause 3\n"
            "CONDITIONS PRECEDENT\n\n"
            "Section 3.01 Initial Conditions. The obligations of each Lender.\n\n"
        )

    def test_finds_articles(self) -> None:
        text = self._make_clause_text()
        outline = DocOutline.from_text(text)
        assert len(outline.articles) >= 2

    def test_finds_sections(self) -> None:
        text = self._make_clause_text()
        outline = DocOutline.from_text(text)
        assert len(outline.sections) >= 3


# ── Fix B: Flat numbered sections ────────────────────────────────────


class TestFlatNumberedSections:
    """Documents with '1. Definitions\\n2. The Commitment\\n...' structure."""

    def _make_flat_text(self) -> str:
        return (
            "CREDIT AGREEMENT\n\n"
            "This Credit Agreement dated as of January 1, 2025.\n\n"
            "1. Definitions. As used in this Agreement, the following terms "
            "shall have the following meanings.\n\n"
            "2. The Commitment. Subject to the terms and conditions herein, "
            "each Lender agrees to make loans to the Borrower.\n\n"
            "3. Conditions Precedent. The obligations of each Lender are subject "
            "to the satisfaction of the following conditions.\n\n"
            "4. Representations and Warranties. The Borrower hereby represents "
            "and warrants to each Lender as follows.\n\n"
            "5. Affirmative Covenants. The Borrower covenants and agrees that "
            "so long as any obligation remains outstanding.\n\n"
            "6. Negative Covenants. The Borrower covenants and agrees that "
            "without the prior written consent of the Required Lenders.\n\n"
            "7. Events of Default. Each of the following shall constitute an "
            "Event of Default under this Agreement.\n\n"
            "8. Miscellaneous Provisions. All notices required to be given "
            "shall be in writing and delivered by courier.\n\n"
        )

    def test_finds_sections(self) -> None:
        text = self._make_flat_text()
        outline = DocOutline.from_text(text)
        assert len(outline.sections) >= 5, (
            f"Expected >= 5 flat sections, got {len(outline.sections)}"
        )

    def test_section_headings(self) -> None:
        text = self._make_flat_text()
        outline = DocOutline.from_text(text)
        headings = [s.heading.lower() for s in outline.sections if s.heading]
        assert any("definition" in h for h in headings)

    def test_section_char_spans(self) -> None:
        text = self._make_flat_text()
        outline = DocOutline.from_text(text)
        for sec in outline.sections:
            assert 0 <= sec.char_start < sec.char_end <= len(text)
            section_text = text[sec.char_start:sec.char_end]
            assert len(section_text.strip()) > 0


# ── Fix C: TOC over-rejection recovery ───────────────────────────────


class TestTocOverRejectionRecovery:
    """Text where all sections look like TOC entries at single-signal threshold."""

    def test_is_toc_entry_min_signals(self) -> None:
        """Verify min_signals parameter works: 1 signal rejects at threshold=1,
        does NOT reject at threshold=2."""
        # Text with a TOC header close by (Signal 1 only)
        text = (
            "TABLE OF CONTENTS\n\n"
            "Some preamble text that fills space so we're within range.\n"
            # 200 chars gap — within the 3K threshold for Signal 1
            + "x" * 100 + "\n"
            "ARTICLE I\nDEFINITIONS\n\n"
            "This is a long prose paragraph that spans many words and is definitely "
            "not a TOC-style short-lined entry. The purpose is to ensure that only "
            "Signal 1 fires (proximity to TOC header) but not Signal 3/4/5.\n\n"
        )
        # Find where ARTICLE I starts
        art_start = text.index("ARTICLE I")
        art_end = art_start + len("ARTICLE I")

        # min_signals=1: should reject (Signal 1 fires)
        assert _is_toc_entry(text, art_start, art_end, min_signals=1) is True

        # min_signals=2: should NOT reject (only Signal 1 fires)
        assert _is_toc_entry(text, art_start, art_end, min_signals=2) is False


# ── Fix D: Ghost section with quoted defined term ────────────────────


class TestGhostSectionQuotedTerm:
    """Headingless sections starting with quoted defined terms should not
    be rejected as ghost sections."""

    def _make_text_with_quoted_start(self) -> str:
        return (
            "CREDIT AGREEMENT\n\n"
            "ARTICLE I\n"
            "DEFINITIONS\n\n"
            'Section 1.01\n'
            '"Borrower" means the company identified as such in the preamble.\n'
            '"Agent" means the administrative agent party hereto.\n\n'
            "Section 1.02 Other Terms. Unless otherwise specified, terms used.\n\n"
            "ARTICLE II\n"
            "THE CREDITS\n\n"
            "Section 2.01 Commitments. Each Lender hereby agrees.\n\n"
        )

    def test_finds_headingless_section(self) -> None:
        text = self._make_text_with_quoted_start()
        outline = DocOutline.from_text(text)
        sec_nums = {s.number for s in outline.sections}
        assert "1.01" in sec_nums, (
            f"Section 1.01 with quoted-term start should be found. Got: {sec_nums}"
        )

    def test_finds_all_sections(self) -> None:
        text = self._make_text_with_quoted_start()
        outline = DocOutline.from_text(text)
        assert len(outline.sections) >= 3


# ── Fix E: Plausibility threshold for flat docs ──────────────────────


class TestPlausibilityFlat:
    """Documents with >40 top-level sections (no article structure)."""

    def _make_high_section_text(self) -> str:
        """Build a document with 50 bare-number sections, no ARTICLE headings."""
        parts = ["CREDIT AGREEMENT\n\n"]
        for i in range(1, 51):
            parts.append(
                f"{i}.01 Section Heading {i}. The Borrower shall comply with this provision "
                f"regarding clause {i} and maintain all requirements specified herein.\n\n"
            )
        return "".join(parts)

    def test_finds_sections_beyond_40(self) -> None:
        """Sections with major number > 40 should be accepted in flat docs."""
        text = self._make_high_section_text()
        outline = DocOutline.from_text(text)
        sec_nums = {s.number for s in outline.sections}
        # Should find section 45.01 (major > 40, which was the old limit)
        assert "45.01" in sec_nums or any("45.01" in n for n in sec_nums), (
            f"Section 45.01 should be found in flat doc. Got {len(outline.sections)} sections."
        )


# ── Fix F: Section synthesis from articles ───────────────────────────


class TestSectionFromArticleSynthesis:
    """When articles are detected but no sub-sections found, synthesize
    one section per article (common in SECTION_TOPLEVEL documents)."""

    def _make_section_toplevel_text(self) -> str:
        """Document using 'SECTION N' as top-level divisions (like a promissory note)."""
        return (
            "PROMISSORY NOTE\n\n"
            "SECTION 1. General. GrafTech International Ltd., a Delaware "
            "corporation (the Issuer), hereby unconditionally promises to pay.\n\n"
            "SECTION 2. Amortization Repayments. The Issuer shall repay this "
            "Note on the last Business Day of each March, June, September "
            "and December.\n\n"
            "SECTION 3. Optional Prepayment. The Issuer may prepay this Note, "
            "in whole or in part, at any time without premium or penalty.\n\n"
            "SECTION 4. Interest. All unpaid principal of this Note shall bear "
            "interest at the applicable rate per annum.\n\n"
            "SECTION 5. Miscellaneous. This Note shall be governed by the laws "
            "of the State of New York.\n\n"
        )

    def test_synthesizes_sections(self) -> None:
        text = self._make_section_toplevel_text()
        outline = DocOutline.from_text(text)
        assert len(outline.sections) >= 4, (
            f"Expected >= 4 synthesized sections, got {len(outline.sections)}"
        )

    def test_section_numbers_format(self) -> None:
        text = self._make_section_toplevel_text()
        outline = DocOutline.from_text(text)
        sec_nums = {s.number for s in outline.sections}
        # Synthesized sections should have X.01 format
        assert "1.01" in sec_nums
        assert "2.01" in sec_nums

    def test_section_headings_preserved(self) -> None:
        text = self._make_section_toplevel_text()
        outline = DocOutline.from_text(text)
        headings = {s.heading for s in outline.sections if s.heading}
        assert any("General" in h for h in headings)

    def test_char_spans_valid(self) -> None:
        text = self._make_section_toplevel_text()
        outline = DocOutline.from_text(text)
        for sec in outline.sections:
            assert 0 <= sec.char_start < sec.char_end <= len(text)

    def _make_article_only_text(self) -> str:
        """Document with ARTICLE headings but no Section X.YY sub-headings."""
        return (
            "CREDIT AGREEMENT\n\n"
            "ARTICLE I\n"
            "DEFINITIONS AND ACCOUNTING TERMS\n\n"
            "As used in this Agreement, the following terms shall have the meanings "
            "assigned to them below. All accounting terms not specifically defined "
            "shall have the meanings given under GAAP.\n\n"
            "ARTICLE II\n"
            "THE CREDITS\n\n"
            "Subject to the terms and conditions set forth herein, each Lender "
            "agrees to make loans to the Borrower from time to time during the "
            "Availability Period.\n\n"
            "ARTICLE III\n"
            "CONDITIONS PRECEDENT\n\n"
            "The obligations of each Lender to make the initial Credit Extension "
            "are subject to the satisfaction of the following conditions.\n\n"
        )

    def test_article_only_synthesizes(self) -> None:
        text = self._make_article_only_text()
        outline = DocOutline.from_text(text)
        assert len(outline.sections) >= 3, (
            f"Expected >= 3 synthesized sections from articles, got {len(outline.sections)}"
        )

    def test_article_only_section_numbers(self) -> None:
        text = self._make_article_only_text()
        outline = DocOutline.from_text(text)
        sec_nums = {s.number for s in outline.sections}
        assert "1.01" in sec_nums
        assert "2.01" in sec_nums
        assert "3.01" in sec_nums


# ── Regression: existing patterns still work ─────────────────────────


class TestRegressionExistingPatterns:
    """Ensure the fixes don't break standard credit agreement parsing."""

    def _make_standard_ca(self) -> str:
        """Standard CA with ARTICLE / Section X.YY pattern."""
        return (
            "CREDIT AGREEMENT\n\n"
            "ARTICLE I\n"
            "DEFINITIONS AND ACCOUNTING TERMS\n\n"
            'Section 1.01 Defined Terms. "Indebtedness" means all obligations.\n'
            '"Consolidated EBITDA" means for any period, net income.\n\n'
            "Section 1.02 Other Interpretive Provisions. Unless otherwise specified.\n\n"
            "ARTICLE II\n"
            "THE CREDITS\n\n"
            "Section 2.01 The Commitments. Subject to the terms and conditions.\n\n"
            "Section 2.02 Loans and Borrowings. Each Loan shall be made as part.\n\n"
            "ARTICLE VII\n"
            "NEGATIVE COVENANTS\n\n"
            "Section 7.01 Indebtedness. The Borrower will not create any Indebtedness.\n\n"
            "Section 7.02 Liens. The Borrower will not create any Lien on any property.\n\n"
        )

    def test_standard_articles(self) -> None:
        text = self._make_standard_ca()
        outline = DocOutline.from_text(text)
        assert len(outline.articles) >= 3
        art_nums = {a.num for a in outline.articles}
        assert {1, 2, 7}.issubset(art_nums)

    def test_standard_sections(self) -> None:
        text = self._make_standard_ca()
        outline = DocOutline.from_text(text)
        assert len(outline.sections) >= 6
        sec_nums = {s.number for s in outline.sections}
        assert "1.01" in sec_nums
        assert "7.01" in sec_nums

    def test_standard_char_spans(self) -> None:
        text = self._make_standard_ca()
        outline = DocOutline.from_text(text)
        for sec in outline.sections:
            assert 0 <= sec.char_start < sec.char_end <= len(text)

    def test_standard_headings(self) -> None:
        text = self._make_standard_ca()
        outline = DocOutline.from_text(text)
        headings = {s.heading for s in outline.sections if s.heading}
        assert any("Defined Terms" in h for h in headings)
        assert any("Liens" in h for h in headings)

    def test_standard_article_titles(self) -> None:
        text = self._make_standard_ca()
        outline = DocOutline.from_text(text)
        titles = {a.title for a in outline.articles if a.title}
        assert any("DEFINITION" in t.upper() for t in titles)

    def test_standard_concepts(self) -> None:
        text = self._make_standard_ca()
        outline = DocOutline.from_text(text)
        concepts = {a.concept for a in outline.articles if a.concept}
        assert "definitions" in concepts
        assert "negative_covenants" in concepts
