"""Tests for structural fingerprint utilities."""

from agent.structural_fingerprint import (
    build_section_fingerprint,
    feature_discrimination_score,
    summarize_fingerprints,
)


def test_build_section_fingerprint_tokens() -> None:
    fp = build_section_fingerprint(
        template_family="kirkland",
        article_num=7,
        section_number="7.01",
        heading="Limitation on Indebtedness",
        text="(a) The Borrower shall not incur debt. Notwithstanding Section 7.02...",
    )
    assert any(token.startswith("template:") for token in fp.tokens)
    assert "marker:notwithstanding" in fp.tokens
    assert fp.features["article_num"] == 7.0


def test_structural_fingerprint_summary_and_discrimination() -> None:
    fp_a = build_section_fingerprint(
        template_family="a",
        article_num=7,
        section_number="7.01",
        heading="Limitation on Indebtedness",
        text="(a) debt restriction",
    )
    fp_b = build_section_fingerprint(
        template_family="b",
        article_num=8,
        section_number="8.02",
        heading="Events of Default",
        text="(a) event of default",
    )
    summary = summarize_fingerprints([fp_a, fp_b])
    assert summary["n"] == 2

    discrimination = feature_discrimination_score({"a": [fp_a], "b": [fp_b]})
    assert "article_num" in discrimination

