"""Tests for agent.classifier — VP classifier port."""
from __future__ import annotations

import pytest

from agent.classifier import (
    ClassificationSignals,
    classify_document_type,
    classify_market_segment,
    extract_classification_signals,
)

# ── ClassificationSignals ────────────────────────────────────────────


class TestClassificationSignals:
    def test_frozen(self) -> None:
        signals = ClassificationSignals(
            word_count=1000,
            definition_count=50,
            article_count=10,
            has_negative_covenants=True,
            negcov_subsection_count=8,
            has_financial_covenants=True,
            has_maintenance_covenants=True,
            has_consolidated_ebitda=True,
            has_available_amount=True,
            has_incremental=True,
            has_grower_baskets=True,
            grower_basket_dollar_amount=100.0,
            basket_language_count=20,
            has_signature_block=True,
            title_text="Test",
        )
        with pytest.raises(AttributeError):
            signals.word_count = 0  # type: ignore[misc]

    def test_all_fields_present(self) -> None:
        fields = ClassificationSignals.__dataclass_fields__
        assert len(fields) == 15


# ── extract_classification_signals ───────────────────────────────────


class TestExtractSignals:
    def _make_ca_text(self) -> str:
        """Build synthetic leveraged credit agreement text."""
        defs = ''.join(f'"Term{i}" means definition number {i}.\n' for i in range(200))
        return (
            'AMENDED AND RESTATED CREDIT AGREEMENT\n\n'
            '"Available Amount" means the sum of $50,000,000.\n'
            '"Incremental Facility" means additional credit.\n'
            + defs
            + 'ARTICLE I DEFINITIONS\n'
            + 'ARTICLE II THE CREDITS\n'
            + 'ARTICLE III CONDITIONS PRECEDENT\n'
            + 'ARTICLE IV REPRESENTATIONS\n'
            + 'ARTICLE V AFFIRMATIVE COVENANTS\n'
            + 'ARTICLE VI INFORMATION COVENANTS\n'
            + 'ARTICLE VII NEGATIVE COVENANTS\n'
            + '7.01 Indebtedness.\n'
            + 'the greater of $100,000,000 and 100% of Consolidated EBITDA\n'
            + '7.02 Liens.\n7.03 Investments.\n7.04 Fundamental Changes.\n'
            + '7.05 Dispositions.\n7.06 Restricted Payments.\n'
            + '7.07 Change of Control.\n7.08 Affiliates.\n'
            + 'ARTICLE VIII FINANCIAL COVENANT\n'
            + 'Consolidated Total Leverage Ratio shall not exceed 5.00 to 1.00\n'
            + 'IN WITNESS WHEREOF\n'
            + ('word ' * 8000)
        )

    def test_leveraged_ca_signals(self) -> None:
        signals = extract_classification_signals(self._make_ca_text())
        assert signals.word_count > 8000
        assert signals.definition_count >= 100
        assert signals.article_count >= 7
        assert signals.has_negative_covenants is True
        assert signals.negcov_subsection_count >= 6
        assert signals.has_grower_baskets is True
        assert signals.has_available_amount is True
        assert signals.has_incremental is True
        assert signals.has_consolidated_ebitda is True
        assert signals.has_maintenance_covenants is True
        assert signals.has_financial_covenants is True
        assert signals.has_signature_block is True

    def test_short_amendment_signals(self) -> None:
        text = 'Amendment No. 1 to Credit Agreement\nword ' * 500
        signals = extract_classification_signals(text)
        assert signals.word_count < 15000
        assert signals.has_grower_baskets is False
        assert signals.has_negative_covenants is False

    def test_definition_patterns(self) -> None:
        text = (
            '"Term A" means something.\n'
            '"Term B" shall mean something else.\n'
            '"Term C" has the meaning assigned.\n'
            '"Term D": means defined.\n'
        )
        signals = extract_classification_signals(text)
        assert signals.definition_count >= 3

    def test_grower_basket_dollar_amount(self) -> None:
        text = 'the greater of $50,000,000 and 100% of Consolidated EBITDA'
        signals = extract_classification_signals(text)
        assert signals.has_grower_baskets is True
        assert signals.grower_basket_dollar_amount is not None

    def test_grower_basket_non_ebitda_metric(self) -> None:
        text = 'the greater of $50,000,000 and 100% of Total Assets'
        signals = extract_classification_signals(text)
        assert signals.has_grower_baskets is True
        # Dollar amount only captured for EBITDA metrics
        assert signals.grower_basket_dollar_amount is None


# ── classify_document_type ───────────────────────────────────────────


class TestClassifyDocType:
    def _signals(self, **overrides: object) -> ClassificationSignals:
        defaults: dict[str, object] = {
            "word_count": 50000,
            "definition_count": 200,
            "article_count": 10,
            "has_negative_covenants": True,
            "negcov_subsection_count": 8,
            "has_financial_covenants": True,
            "has_maintenance_covenants": True,
            "has_consolidated_ebitda": True,
            "has_available_amount": True,
            "has_incremental": True,
            "has_grower_baskets": True,
            "grower_basket_dollar_amount": 100.0,
            "basket_language_count": 20,
            "has_signature_block": True,
            "title_text": "Credit Agreement",
        }
        defaults.update(overrides)
        return ClassificationSignals(**defaults)  # type: ignore[arg-type]

    def test_ar_credit_agreement(self) -> None:
        signals = self._signals(
            title_text="Amended and Restated Credit Agreement"
        )
        doc_type, conf, _ = classify_document_type("test.htm", signals)
        assert doc_type == "credit_agreement"
        assert conf == "high"

    def test_credit_agreement_large(self) -> None:
        signals = self._signals(word_count=60000)
        doc_type, _, _ = classify_document_type("test.htm", signals)
        assert doc_type == "credit_agreement"

    def test_amendment_no_ca(self) -> None:
        signals = self._signals(
            title_text="Amendment No. 1",
            word_count=5000,
            definition_count=10,
            article_count=2,
        )
        doc_type, _, _ = classify_document_type("amendment_1.htm", signals)
        assert doc_type == "amendment"

    def test_waiver_no_ca(self) -> None:
        signals = self._signals(
            title_text="Limited Waiver and Consent",
            word_count=3000,
            definition_count=5,
            article_count=1,
        )
        doc_type, _, _ = classify_document_type("waiver.htm", signals)
        assert doc_type == "waiver"

    def test_intercreditor(self) -> None:
        signals = self._signals(
            title_text="Intercreditor Agreement",
            word_count=15000,
            definition_count=40,
        )
        doc_type, _, _ = classify_document_type("intercreditor.htm", signals)
        assert doc_type == "intercreditor"

    def test_guaranty(self) -> None:
        signals = self._signals(
            title_text="Guaranty Agreement",
            word_count=5000,
            definition_count=10,
        )
        doc_type, _, _ = classify_document_type("guaranty.htm", signals)
        assert doc_type == "guaranty"

    def test_supplement_small(self) -> None:
        signals = self._signals(
            title_text="Lender Supplement",
            word_count=2000,
            definition_count=5,
        )
        doc_type, _, _ = classify_document_type("supplement.htm", signals)
        assert doc_type == "supplement"

    def test_structural_fallback(self) -> None:
        signals = self._signals(
            title_text="Some Document",
            word_count=20000,
            article_count=8,
            definition_count=50,
        )
        doc_type, _, _ = classify_document_type("unknown.htm", signals)
        assert doc_type == "credit_agreement"

    def test_amendment_to_ar_credit_agreement(self) -> None:
        """Amendment No. X to A&R CA → amendment, even if doc is large."""
        signals = self._signals(
            title_text="Amendment No. 3 to Amended and Restated Credit Agreement",
            word_count=60000,
            definition_count=250,
        )
        doc_type, conf, reasons = classify_document_type("test.htm", signals)
        assert doc_type == "amendment"
        assert conf == "high"
        assert any("Amendment to Credit Agreement" in r for r in reasons)

    def test_first_amendment_to_credit_agreement(self) -> None:
        """Ordinal amendment to CA → amendment."""
        signals = self._signals(
            title_text="First Amendment to Credit Agreement",
            word_count=40000,
            definition_count=180,
        )
        doc_type, conf, _ = classify_document_type("test.htm", signals)
        assert doc_type == "amendment"
        assert conf == "high"

    def test_amendment_to_third_ar_ca(self) -> None:
        """Real EDGAR pattern: Amendment No. 1 to Third A&R CA."""
        signals = self._signals(
            title_text=(
                "AMENDMENT NO. 1 to THIRD AMENDED AND RESTATED "
                "CREDIT AGREEMENT"
            ),
            word_count=80000,
        )
        doc_type, _, _ = classify_document_type("test.htm", signals)
        assert doc_type == "amendment"

    def test_amendment_and_waiver_to_ca(self) -> None:
        """Amendment and Waiver to CA → amendment."""
        signals = self._signals(
            title_text="Amendment and Waiver to Credit Agreement",
            word_count=35000,
        )
        doc_type, _, _ = classify_document_type("test.htm", signals)
        assert doc_type == "amendment"

    def test_standalone_ar_ca_not_amendment(self) -> None:
        """Standalone A&R CA must NOT be reclassified as amendment."""
        signals = self._signals(
            title_text="Amended and Restated Credit Agreement",
        )
        doc_type, conf, _ = classify_document_type("test.htm", signals)
        assert doc_type == "credit_agreement"
        assert conf == "high"

    def test_amendment_to_ca_large_with_annex(self) -> None:
        """Large amendment (full CA attached as annex) still classified as amendment."""
        signals = self._signals(
            title_text="Amendment No. 5 to Second Amended and Restated Credit Agreement",
            word_count=90000,
            definition_count=300,
            article_count=12,
            has_grower_baskets=True,
            has_negative_covenants=True,
            negcov_subsection_count=10,
        )
        doc_type, conf, _ = classify_document_type(
            "ex10d2_amendment.htm", signals
        )
        assert doc_type == "amendment"
        assert conf == "high"

    def test_default_other(self) -> None:
        signals = self._signals(
            title_text="Random Filing",
            word_count=1000,
            definition_count=2,
            article_count=0,
            has_negative_covenants=False,
            has_signature_block=False,
        )
        doc_type, _, _ = classify_document_type("random.htm", signals)
        assert doc_type == "other"


# ── classify_market_segment ──────────────────────────────────────────


class TestClassifyMarketSegment:
    def _signals(self, **overrides: object) -> ClassificationSignals:
        defaults: dict[str, object] = {
            "word_count": 50000,
            "definition_count": 200,
            "article_count": 10,
            "has_negative_covenants": True,
            "negcov_subsection_count": 8,
            "has_financial_covenants": True,
            "has_maintenance_covenants": True,
            "has_consolidated_ebitda": True,
            "has_available_amount": True,
            "has_incremental": True,
            "has_grower_baskets": True,
            "grower_basket_dollar_amount": 100.0,
            "basket_language_count": 20,
            "has_signature_block": True,
            "title_text": "Credit Agreement",
        }
        defaults.update(overrides)
        return ClassificationSignals(**defaults)  # type: ignore[arg-type]

    def test_clear_leveraged(self) -> None:
        """Grower baskets + NegCov >= 6 + defs >= 150 = leveraged high."""
        signals = self._signals()
        seg, conf, _ = classify_market_segment(signals)
        assert seg == "leveraged"
        assert conf == "high"

    def test_leveraged_medium_grower_only(self) -> None:
        """Grower baskets + NegCov >= 4 = leveraged medium."""
        signals = self._signals(
            negcov_subsection_count=4,
            definition_count=80,
        )
        seg, conf, _ = classify_market_segment(signals)
        assert seg == "leveraged"
        assert conf == "medium"

    def test_investment_grade_no_negcov_no_grower(self) -> None:
        """No negative covenants + no grower baskets = IG high."""
        signals = self._signals(
            has_negative_covenants=False,
            negcov_subsection_count=0,
            has_grower_baskets=False,
            grower_basket_dollar_amount=None,
            has_available_amount=False,
            has_incremental=False,
            has_maintenance_covenants=False,
            definition_count=50,
        )
        seg, conf, _ = classify_market_segment(signals)
        assert seg == "investment_grade"
        assert conf == "high"

    def test_investment_grade_medium(self) -> None:
        """No grower, few NegCov, few defs, no leveraged features."""
        signals = self._signals(
            has_negative_covenants=True,
            has_grower_baskets=False,
            grower_basket_dollar_amount=None,
            negcov_subsection_count=2,
            definition_count=50,
            has_available_amount=False,
            has_incremental=False,
        )
        seg, conf, _ = classify_market_segment(signals)
        assert seg == "investment_grade"
        assert conf == "medium"

    def test_uncertain_mixed(self) -> None:
        """Mixed signals that don't clearly resolve."""
        # Enough leveraged features to not be IG, but not enough for leveraged
        signals = self._signals(
            has_negative_covenants=True,
            has_grower_baskets=True,
            grower_basket_dollar_amount=None,
            negcov_subsection_count=3,
            definition_count=80,
            has_available_amount=False,
            has_incremental=False,
            has_maintenance_covenants=False,
        )
        seg, _, _ = classify_market_segment(signals)
        # Grower baskets + negcov 3 + defs 80 doesn't hit any clear bucket
        # because grower + (negcov >= 4 or defs >= 100) is the medium threshold
        assert seg in ("leveraged", "uncertain")


# ── End-to-end ───────────────────────────────────────────────────────


class TestEndToEnd:
    def test_leveraged_ca_pipeline(self) -> None:
        """Full pipeline: text -> signals -> doc_type -> segment."""
        defs = ''.join(f'"Term{i}" means definition number {i}.\n' for i in range(200))
        full_text = (
            'AMENDED AND RESTATED CREDIT AGREEMENT\n'
            '"Available Amount" means sum.\n'
            '"Incremental Facility" means additional.\n'
            + defs
            + 'ARTICLE I DEFINITIONS\n'
            + 'ARTICLE II THE CREDITS\n'
            + 'ARTICLE III CONDITIONS\n'
            + 'ARTICLE IV REPRESENTATIONS\n'
            + 'ARTICLE V AFFIRMATIVE COVENANTS\n'
            + 'ARTICLE VI INFORMATION COVENANTS\n'
            + 'ARTICLE VII NEGATIVE COVENANTS\n'
            + '7.01 Indebtedness.\n'
            + 'the greater of $100,000,000 and 100% of Consolidated EBITDA\n'
            + '7.02 Liens.\n7.03 Investments.\n7.04 Fundamental Changes.\n'
            + '7.05 Dispositions.\n7.06 Restricted Payments.\n'
            + '7.07 Change of Control.\n7.08 Affiliates.\n'
            + 'ARTICLE VIII FINANCIAL COVENANT\n'
            + 'Consolidated Total Leverage Ratio shall not exceed 5.00 to 1.00\n'
            + 'IN WITNESS WHEREOF\n'
            + ('word ' * 8000)
        )

        signals = extract_classification_signals(full_text, "test_ca.htm")
        doc_type, dt_conf, _ = classify_document_type("test_ca.htm", signals)
        segment, _, _ = classify_market_segment(signals)

        assert doc_type == "credit_agreement"
        assert dt_conf == "high"
        assert segment == "leveraged"
