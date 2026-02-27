"""Tests for agent.document_processor — shared NLP pipeline module."""
from __future__ import annotations

import json

import pytest

from agent.document_processor import (
    ACCESSION_RE,
    CIK_DIR_RE,
    DocumentResult,
    SidecarMetadata,
    accession_sort_key,
    compute_doc_id,
    dedup_by_cik,
    extract_accession,
    extract_cik,
    is_cohort_included,
    normalize_accession,
    normalize_date_value,
    process_document_text,
)

# ── extract_cik ─────────────────────────────────────────────────────


class TestExtractCik:
    def test_local_path(self) -> None:
        path = "corpus/cik=0001234567/0001234567-22-012345.htm"
        assert extract_cik(path) == "0001234567"

    def test_s3_key(self) -> None:
        key = "corpus-v2/cik=0009876543/0009876543-23-001234.htm"
        assert extract_cik(key) == "0009876543"

    def test_no_cik(self) -> None:
        assert extract_cik("random/path/file.htm") == ""

    def test_multiple_cik_takes_first(self) -> None:
        path = "corpus/cik=0001111111/subdir/cik=0002222222/file.htm"
        assert extract_cik(path) == "0001111111"

    def test_cik_regex_requires_10_digits(self) -> None:
        assert extract_cik("cik=12345/file.htm") == ""
        assert extract_cik("cik=0000012345/file.htm") == "0000012345"


# ── extract_accession ───────────────────────────────────────────────


class TestExtractAccession:
    def test_from_filename(self) -> None:
        path = "corpus/cik=0001234567/0001234567-22-012345.htm"
        assert extract_accession(path) == "0001234567-22-012345"

    def test_from_s3_key(self) -> None:
        key = "corpus-v2/cik=0009876543/0009876543-23-001234.htm"
        assert extract_accession(key) == "0009876543-23-001234"

    def test_no_accession(self) -> None:
        assert extract_accession("corpus/cik=0001234567/readme.txt") == ""

    def test_accession_in_complex_filename(self) -> None:
        path = "corpus/cik=0001234567/ex10d2_0001234567-21-000999.htm"
        assert extract_accession(path) == "0001234567-21-000999"

    def test_undashed_accession(self) -> None:
        """EDGAR filenames use 18-digit undashed accessions."""
        path = "corpus/cik=0000001750/000110465918013433_a18-7233_1ex10d2.htm"
        assert extract_accession(path) == "0001104659-18-013433"

    def test_undashed_returns_dashed(self) -> None:
        path = "documents/cik=0001234567/000123456722012345_ex10.htm"
        result = extract_accession(path)
        assert result == "0001234567-22-012345"
        assert "-" in result  # Always returns dashed form


# ── normalize_accession ─────────────────────────────────────────────


class TestNormalizeAccession:
    def test_dashed_passthrough(self) -> None:
        assert normalize_accession("0001104659-18-013433") == "0001104659-18-013433"

    def test_undashed_to_dashed(self) -> None:
        assert normalize_accession("000110465918013433") == "0001104659-18-013433"

    def test_whitespace_stripped(self) -> None:
        assert normalize_accession("  000110465918013433  ") == "0001104659-18-013433"

    def test_unrecognized_passthrough(self) -> None:
        assert normalize_accession("not-an-accession") == "not-an-accession"

    def test_empty_string(self) -> None:
        assert normalize_accession("") == ""


# ── normalize_date_value ────────────────────────────────────────────


class TestNormalizeDateValue:
    def test_iso_date(self) -> None:
        assert normalize_date_value("2023-06-15") == "2023-06-15"

    def test_iso_datetime(self) -> None:
        assert normalize_date_value("2023-06-15T14:30:00Z") == "2023-06-15"

    def test_year_only_returns_none(self) -> None:
        assert normalize_date_value("2023") is None

    def test_none_input(self) -> None:
        assert normalize_date_value(None) is None

    def test_empty_string(self) -> None:
        assert normalize_date_value("") is None

    def test_whitespace_only(self) -> None:
        assert normalize_date_value("  ") is None

    def test_integer_year(self) -> None:
        assert normalize_date_value(2023) is None

    def test_non_date_string(self) -> None:
        assert normalize_date_value("not-a-date") is None


# ── compute_doc_id ──────────────────────────────────────────────────


class TestComputeDocId:
    def test_deterministic(self) -> None:
        text = "This is a test document for hashing."
        assert compute_doc_id(text) == compute_doc_id(text)

    def test_different_text_different_id(self) -> None:
        assert compute_doc_id("text A") != compute_doc_id("text B")

    def test_length_16_hex(self) -> None:
        doc_id = compute_doc_id("test")
        assert len(doc_id) == 16
        assert all(c in "0123456789abcdef" for c in doc_id)

    def test_empty_string_works(self) -> None:
        doc_id = compute_doc_id("")
        assert len(doc_id) == 16


# ── accession_sort_key ──────────────────────────────────────────────


class TestAccessionSortKey:
    def test_standard_filename(self) -> None:
        # cik=10 digits, year=22, seq=012345
        key = accession_sort_key("cik=0001234567/000123456722012345.htm")
        year, seq, _ = key
        assert year == 22
        assert seq == 12345

    def test_no_accession_prefix(self) -> None:
        key = accession_sort_key("corpus/readme.txt")
        assert key == (0, 0, "readme.txt")

    def test_sort_order_newer_wins(self) -> None:
        older = accession_sort_key("cik=0001234567/000123456720000001.htm")
        newer = accession_sort_key("cik=0001234567/000123456723000001.htm")
        assert newer > older

    def test_s3_key(self) -> None:
        key = accession_sort_key("corpus-v2/cik=0001234567/000123456722999999.htm")
        year, seq, _ = key
        assert year == 22
        assert seq == 999999


# ── is_cohort_included ──────────────────────────────────────────────


class TestIsCohortIncluded:
    def test_leveraged_ca_high_high(self) -> None:
        assert is_cohort_included("credit_agreement", "high", "leveraged", "high") is True

    def test_leveraged_ca_medium_medium(self) -> None:
        assert is_cohort_included("credit_agreement", "medium", "leveraged", "medium") is True

    def test_amendment_excluded(self) -> None:
        assert is_cohort_included("amendment", "high", "leveraged", "high") is False

    def test_investment_grade_excluded(self) -> None:
        assert is_cohort_included("credit_agreement", "high", "investment_grade", "high") is False

    def test_low_confidence_excluded(self) -> None:
        assert is_cohort_included("credit_agreement", "low", "leveraged", "high") is False
        assert is_cohort_included("credit_agreement", "high", "leveraged", "low") is False

    def test_other_doc_type_excluded(self) -> None:
        assert is_cohort_included("other", "high", "leveraged", "high") is False

    def test_uncertain_segment_excluded(self) -> None:
        assert is_cohort_included("credit_agreement", "high", "uncertain", "medium") is False


# ── dedup_by_cik ────────────────────────────────────────────────────


class TestDedupByCik:
    def test_single_per_cik_unchanged(self) -> None:
        keys = [
            "corpus/cik=0001111111/000111111122000001.htm",
            "corpus/cik=0002222222/000222222222000001.htm",
        ]
        result = dedup_by_cik(keys)
        assert len(result) == 2

    def test_keeps_newer_filing(self) -> None:
        older = "corpus/cik=0001111111/000111111120000001.htm"
        newer = "corpus/cik=0001111111/000111111123000001.htm"
        result = dedup_by_cik([older, newer])
        assert len(result) == 1
        assert result[0] == newer

    def test_no_cik_always_kept(self) -> None:
        keys = [
            "corpus/no_cik_dir/file1.htm",
            "corpus/no_cik_dir/file2.htm",
        ]
        result = dedup_by_cik(keys)
        assert len(result) == 2

    def test_s3_keys(self) -> None:
        older = "corpus-v2/cik=0001111111/000111111120000001.htm"
        newer = "corpus-v2/cik=0001111111/000111111123000050.htm"
        result = dedup_by_cik([older, newer])
        assert len(result) == 1
        assert result[0] == newer

    def test_mixed_cik_and_no_cik(self) -> None:
        keys = [
            "corpus/cik=0001111111/000111111120000001.htm",
            "corpus/cik=0001111111/000111111123000001.htm",
            "corpus/other/file.htm",
        ]
        result = dedup_by_cik(keys)
        assert len(result) == 2  # 1 kept per CIK + 1 no-CIK

    def test_verbose_does_not_crash(self) -> None:
        keys = [
            "corpus/cik=0001111111/000111111120000001.htm",
            "corpus/cik=0001111111/000111111123000001.htm",
        ]
        result = dedup_by_cik(keys, verbose=True)
        assert len(result) == 1

    def test_empty_list(self) -> None:
        assert dedup_by_cik([]) == []

    def test_result_sorted(self) -> None:
        keys = [
            "corpus/cik=0002222222/000222222222000001.htm",
            "corpus/cik=0001111111/000111111122000001.htm",
        ]
        result = dedup_by_cik(keys)
        assert result == sorted(result)


# ── SidecarMetadata ─────────────────────────────────────────────────


class TestSidecarMetadata:
    def test_frozen(self) -> None:
        sc = SidecarMetadata(
            company_name="Foo Inc.",
            cik="0001234567",
            accession="0001234567-22-012345",
        )
        with pytest.raises(AttributeError):
            sc.cik = "9999999999"  # type: ignore[misc]

    def test_defaults_empty(self) -> None:
        sc = SidecarMetadata()
        assert sc.company_name == ""
        assert sc.cik == ""
        assert sc.accession == ""


# ── DocumentResult ──────────────────────────────────────────────────


class TestDocumentResult:
    def test_to_dict_keys(self) -> None:
        result = DocumentResult(
            doc={"doc_id": "abc"},
            sections=[{"s": 1}],
            clauses=[],
            definitions=[],
            section_texts=[],
            section_features=[],
            clause_features=[],
        )
        d = result.to_dict()
        assert set(d.keys()) == {
            "doc",
            "articles",
            "sections",
            "clauses",
            "definitions",
            "section_texts",
            "section_features",
            "clause_features",
        }
        assert d["doc"]["doc_id"] == "abc"
        assert d["sections"] == [{"s": 1}]

    def test_frozen(self) -> None:
        result = DocumentResult(
            doc={}, sections=[], clauses=[], definitions=[],
            section_texts=[], section_features=[], clause_features=[],
        )
        with pytest.raises(AttributeError):
            result.doc = {"x": 1}  # type: ignore[misc]


# ── process_document_text ───────────────────────────────────────────


def _make_leveraged_ca_html() -> str:
    """Build minimal HTML for a leveraged credit agreement.

    Includes enough structure to exercise the full NLP pipeline:
    definitions, articles, negative covenants, grower baskets,
    financial covenants, and a signature block.
    """
    defs = "".join(
        f'<p>&quot;Term{i}&quot; means definition number {i}.</p>\n'
        for i in range(200)
    )
    return (
        "<html><body>"
        "<h1>AMENDED AND RESTATED CREDIT AGREEMENT</h1>\n"
        '<p>&quot;Available Amount&quot; means the sum of $50,000,000.</p>\n'
        '<p>&quot;Incremental Facility&quot; means additional credit.</p>\n'
        + defs
        + "<h2>ARTICLE I DEFINITIONS</h2>\n"
        + "<h2>ARTICLE II THE CREDITS</h2>\n"
        + "<h2>ARTICLE III CONDITIONS PRECEDENT</h2>\n"
        + "<h2>ARTICLE IV REPRESENTATIONS</h2>\n"
        + "<h2>ARTICLE V AFFIRMATIVE COVENANTS</h2>\n"
        + "<h2>ARTICLE VI INFORMATION COVENANTS</h2>\n"
        + "<h2>ARTICLE VII NEGATIVE COVENANTS</h2>\n"
        + "<p>7.01 Indebtedness.</p>\n"
        + "<p>the greater of $100,000,000 and 100% of Consolidated EBITDA</p>\n"
        + "<p>7.02 Liens.</p>\n<p>7.03 Investments.</p>\n"
        + "<p>7.04 Fundamental Changes.</p>\n"
        + "<p>7.05 Dispositions.</p>\n<p>7.06 Restricted Payments.</p>\n"
        + "<p>7.07 Change of Control.</p>\n<p>7.08 Affiliates.</p>\n"
        + "<h2>ARTICLE VIII FINANCIAL COVENANT</h2>\n"
        + "<p>Consolidated Total Leverage Ratio shall not exceed 5.00 to 1.00</p>\n"
        + "<p>IN WITNESS WHEREOF</p>\n"
        + ("<p>word </p>" * 8000)
        + "</body></html>"
    )


class TestProcessDocumentText:
    def test_returns_none_for_empty_html(self) -> None:
        result = process_document_text(
            html="", path_or_key="test.htm", filename="test.htm",
        )
        assert result is None

    def test_returns_none_for_short_html(self) -> None:
        result = process_document_text(
            html="<html><body>short</body></html>",
            path_or_key="test.htm",
            filename="test.htm",
        )
        assert result is None

    def test_full_pipeline_leveraged_ca(self) -> None:
        html = _make_leveraged_ca_html()
        result = process_document_text(
            html=html,
            path_or_key="corpus/cik=0001234567/0001234567-22-012345.htm",
            filename="0001234567-22-012345.htm",
        )
        assert result is not None
        doc = result.doc
        assert doc["doc_id"]  # non-empty
        assert len(doc["doc_id"]) == 16
        assert doc["cik"] == "0001234567"
        assert doc["accession"] == "0001234567-22-012345"
        assert doc["doc_type"] == "credit_agreement"
        assert doc["market_segment"] == "leveraged"
        assert doc["cohort_included"] is True
        assert doc["word_count"] > 8000
        assert doc["text_length"] > 0

    def test_full_pipeline_seven_record_lists(self) -> None:
        html = _make_leveraged_ca_html()
        result = process_document_text(
            html=html,
            path_or_key="corpus/cik=0001234567/0001234567-22-012345.htm",
            filename="0001234567-22-012345.htm",
        )
        assert result is not None
        # Sections should be populated (articles create sections)
        assert len(result.sections) > 0
        # Each section has a corresponding text and feature record
        assert len(result.section_texts) == len(result.sections)
        assert len(result.section_features) == len(result.sections)
        # Definitions should be populated
        assert len(result.definitions) >= 100
        # to_dict roundtrip
        d = result.to_dict()
        assert len(d) == 8

    def test_sidecar_overrides_path_metadata(self) -> None:
        html = _make_leveraged_ca_html()
        sidecar = SidecarMetadata(
            company_name="Override Corp.",
            cik="9999999999",
            accession="9999999999-23-000001",
        )
        result = process_document_text(
            html=html,
            path_or_key="corpus/cik=0001234567/0001234567-22-012345.htm",
            filename="0001234567-22-012345.htm",
            sidecar=sidecar,
        )
        assert result is not None
        assert result.doc["cik"] == "9999999999"
        assert result.doc["accession"] == "9999999999-23-000001"

    def test_cohort_only_nlp_skips_sections(self) -> None:
        """Non-cohort doc with cohort_only_nlp=True should skip NLP."""
        # Build a short amendment that's NOT cohort-included
        html = (
            "<html><body>"
            "<h1>Amendment No. 1 to Credit Agreement</h1>\n"
            + ("<p>word </p>" * 500)
            + "</body></html>"
        )
        result = process_document_text(
            html=html,
            path_or_key="corpus/cik=0001234567/0001234567-22-012345.htm",
            filename="0001234567-22-012345.htm",
            cohort_only_nlp=True,
        )
        assert result is not None
        doc = result.doc
        assert doc["cohort_included"] is False
        # NLP should have been skipped
        assert doc["section_count"] == 0
        assert doc["clause_count"] == 0
        assert doc["definition_count"] == 0
        assert result.sections == []
        assert result.clauses == []
        assert result.definitions == []
        assert result.section_texts == []
        assert result.section_features == []
        assert result.clause_features == []

    def test_cohort_only_nlp_runs_for_cohort(self) -> None:
        """Cohort doc with cohort_only_nlp=True should still run full NLP."""
        html = _make_leveraged_ca_html()
        result = process_document_text(
            html=html,
            path_or_key="corpus/cik=0001234567/0001234567-22-012345.htm",
            filename="0001234567-22-012345.htm",
            cohort_only_nlp=True,
        )
        assert result is not None
        assert result.doc["cohort_included"] is True
        assert result.doc["section_count"] > 0
        assert len(result.definitions) >= 100

    def test_doc_id_deterministic(self) -> None:
        html = _make_leveraged_ca_html()
        r1 = process_document_text(
            html=html, path_or_key="path/a.htm", filename="a.htm",
        )
        r2 = process_document_text(
            html=html, path_or_key="path/b.htm", filename="b.htm",
        )
        assert r1 is not None and r2 is not None
        # Same HTML content → same doc_id
        assert r1.doc["doc_id"] == r2.doc["doc_id"]

    def test_section_parser_mode_populated(self) -> None:
        html = _make_leveraged_ca_html()
        result = process_document_text(
            html=html,
            path_or_key="test.htm",
            filename="test.htm",
        )
        assert result is not None
        assert result.doc["section_parser_mode"] in (
            "doc_outline", "regex_fallback", "none",
        )
        trace = json.loads(str(result.doc.get("section_parser_trace", "{}")))
        assert isinstance(trace, dict)
        assert "mode" in trace
        assert "outline_sections" in trace

    def test_filing_date_from_filename(self) -> None:
        """Filing date extraction is attempted from filename."""
        html = _make_leveraged_ca_html()
        result = process_document_text(
            html=html,
            path_or_key="corpus/cik=0001234567/0001234567-22-012345.htm",
            filename="0001234567-22-012345.htm",
        )
        assert result is not None
        # filing_date may or may not parse from an accession filename,
        # but the field should exist
        assert "filing_date" in result.doc

    def test_sidecar_partial_override(self) -> None:
        """Sidecar with only CIK overrides CIK but path accession remains."""
        html = _make_leveraged_ca_html()
        sidecar = SidecarMetadata(cik="8888888888")
        result = process_document_text(
            html=html,
            path_or_key="corpus/cik=0001234567/0001234567-22-012345.htm",
            filename="0001234567-22-012345.htm",
            sidecar=sidecar,
        )
        assert result is not None
        assert result.doc["cik"] == "8888888888"
        # Accession not overridden, falls back to path
        assert result.doc["accession"] == "0001234567-22-012345"


# ── Regex constants ─────────────────────────────────────────────────


class TestRegexConstants:
    def test_cik_dir_re(self) -> None:
        m = CIK_DIR_RE.search("corpus/cik=0001234567/file.htm")
        assert m is not None
        assert m.group(1) == "0001234567"

    def test_accession_re(self) -> None:
        m = ACCESSION_RE.search("0001234567-22-012345")
        assert m is not None
        assert m.group(1) == "0001234567-22-012345"
