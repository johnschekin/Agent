"""Shared document processing pipeline for corpus build scripts.

Extracts the core NLP processing logic shared by both the local
(``build_corpus_index.py``) and Ray (``build_corpus_ray_v2.py``)
pipelines.  I/O (filesystem vs S3) remains in each pipeline script;
this module operates on already-loaded HTML strings.

The single entry point is :func:`process_document_text`, which takes
raw HTML and returns a :class:`DocumentResult` with all 7 record
lists (documents, sections, clauses, definitions, section_text,
section_features, clause_features).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from agent.classifier import (
    classify_document_type,
    classify_market_segment,
    extract_classification_signals,
)
from agent.clause_parser import ClauseNode, parse_clauses
from agent.definitions import DefinedTerm, extract_definitions
from agent.doc_parser import DocOutline
from agent.html_utils import normalize_html, strip_html
from agent.materialized_features import build_clause_feature, build_section_feature
from agent.metadata import (
    extract_admin_agent,
    extract_borrower,
    extract_effective_date,
    extract_facility_sizes,
    extract_filing_date,
    extract_grower_baskets,
)
from agent.parsing_types import OutlineSection

# ---------------------------------------------------------------------------
# Regex constants (used by both pipelines)
# ---------------------------------------------------------------------------

CIK_DIR_RE: re.Pattern[str] = re.compile(r"cik=(\d{10})")
ACCESSION_RE: re.Pattern[str] = re.compile(r"(\d{10}-\d{2}-\d{6})")
# Undashed accession: 18 consecutive digits at the start of a filename stem
# (e.g. "000110465918013433" from "000110465918013433_ex10d2.htm")
ACCESSION_UNDASHED_RE: re.Pattern[str] = re.compile(r"^(\d{18})")
ISO_DATE_RE: re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YEAR_ONLY_RE: re.Pattern[str] = re.compile(r"^\d{4}$")
# Accession year: first 10 digits = filer CIK, next 2 = year, next 6 = sequence
ACCESSION_YEAR_RE: re.Pattern[str] = re.compile(r"^(\d{10})(\d{2})(\d{6})")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def extract_cik(path_or_key: str) -> str:
    """Extract CIK from a path or S3 key containing ``cik=XXXXXXXXXX``."""
    m = CIK_DIR_RE.search(path_or_key)
    return m.group(1) if m else ""


def _undashed_to_dashed(undashed: str) -> str:
    """Convert 18-digit undashed accession to dashed SEC canonical form."""
    return f"{undashed[:10]}-{undashed[10:12]}-{undashed[12:]}"


def normalize_accession(raw: str) -> str:
    """Normalize an accession to dashed SEC canonical form.

    Accepts both ``0001104659-18-013433`` (dashed) and
    ``000110465918013433`` (undashed) and returns dashed.
    Returns the input unchanged if it doesn't match either pattern.
    """
    raw = raw.strip()
    if ACCESSION_RE.fullmatch(raw):
        return raw
    if re.fullmatch(r"\d{18}", raw):
        return _undashed_to_dashed(raw)
    return raw


def extract_accession(path_or_key: str) -> str:
    """Extract accession number from a filename or path/S3 key.

    Handles both dashed (``0001104659-18-013433``) and undashed
    (``000110465918013433``) accession formats.  Always returns the
    dashed SEC canonical form.
    """
    stem = PurePosixPath(path_or_key).stem
    # Try dashed format first (canonical)
    m = ACCESSION_RE.search(stem)
    if m:
        return m.group(1)
    # Try undashed 18-digit prefix (common in EDGAR filenames)
    m = ACCESSION_UNDASHED_RE.match(stem)
    if m:
        return _undashed_to_dashed(m.group(1))
    # Fallback: search full path for dashed format
    m = ACCESSION_RE.search(path_or_key)
    return m.group(1) if m else ""


def normalize_date_value(value: Any) -> str | None:
    """Normalize metadata date values to DuckDB DATE-compatible YYYY-MM-DD.

    Returns None for partial/invalid dates (e.g., "2022").
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if ISO_DATE_RE.match(raw):
        return raw
    # Common timestamp case: keep date prefix when full ISO datetime appears.
    if len(raw) >= 10 and ISO_DATE_RE.match(raw[:10]):
        return raw[:10]
    # Year-only values are too ambiguous for DATE columns.
    if YEAR_ONLY_RE.match(raw):
        return None
    return None


def compute_doc_id(normalized_text: str) -> str:
    """Compute deterministic content-addressed doc_id.

    Uses SHA-256 of normalized text and truncates to 16 hex chars.
    """
    h = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return h[:16]


def accession_sort_key(path_or_key: str) -> tuple[int, int, str]:
    """Extract (year, sequence, filename) sort key from accession prefix."""
    name = PurePosixPath(path_or_key).name
    m = ACCESSION_YEAR_RE.match(name)
    if m:
        return (int(m.group(2)), int(m.group(3)), name)
    # Fallback: no accession prefix — sort by filename (latest alphabetically)
    return (0, 0, name)


def is_cohort_included(
    doc_type: str,
    dt_confidence: str,
    market_segment: str,
    seg_confidence: str,
) -> bool:
    """Determine if a document belongs in the discovery cohort.

    Only leveraged credit agreements with medium+ confidence enter the
    discovery corpus.
    """
    return (
        doc_type == "credit_agreement"
        and market_segment == "leveraged"
        and dt_confidence in ("high", "medium")
        and seg_confidence in ("high", "medium")
    )


def dedup_by_cik(
    keys: list[str],
    *,
    verbose: bool = False,
) -> list[str]:
    """Keep only the most recent file per CIK directory.

    "Most recent" is determined by the filing year and sequence number
    encoded in the accession-number prefix of the filename.

    Works identically with local filesystem paths and S3 keys since
    both use the ``cik=XXXXXXXXXX`` directory convention.
    """
    cik_keys: dict[str, list[str]] = {}
    no_cik: list[str] = []
    for k in keys:
        cik = extract_cik(k)
        if cik:
            cik_keys.setdefault(cik, []).append(k)
        else:
            no_cik.append(k)

    kept: list[str] = list(no_cik)

    for _cik, cik_paths in sorted(cik_keys.items()):
        if len(cik_paths) == 1:
            kept.append(cik_paths[0])
            continue
        # Pick the most recent by accession year+sequence (descending)
        best = cik_paths[0]
        best_key = accession_sort_key(best)
        for p in cik_paths[1:]:
            key = accession_sort_key(p)
            if key > best_key:
                best = p
                best_key = key
        kept.append(best)

    kept.sort()

    if verbose:
        dropped = len(keys) - len(kept)
        print(
            f"  CIK dedup: {len(keys)} -> {len(kept)} files "
            f"({dropped} duplicates removed, {len(cik_keys)} CIKs)",
            file=sys.stderr,
        )
    return kept


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SidecarMetadata:
    """Metadata extracted from a .meta.json sidecar file."""

    company_name: str = ""
    cik: str = ""
    accession: str = ""


@dataclass(frozen=True, slots=True)
class DocumentResult:
    """Result of processing a single document through the NLP pipeline."""

    doc: dict[str, Any]
    sections: list[dict[str, Any]]
    clauses: list[dict[str, Any]]
    definitions: list[dict[str, Any]]
    section_texts: list[dict[str, Any]]
    section_features: list[dict[str, Any]]
    clause_features: list[dict[str, Any]]
    articles: list[dict[str, Any]] = ()  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        """Convert to the dict format expected by pipeline consumers."""
        return {
            "doc": self.doc,
            "articles": list(self.articles),
            "sections": self.sections,
            "clauses": self.clauses,
            "definitions": self.definitions,
            "section_texts": self.section_texts,
            "section_features": self.section_features,
            "clause_features": self.clause_features,
        }


# ---------------------------------------------------------------------------
# Core processing function
# ---------------------------------------------------------------------------


def process_document_text(
    *,
    html: str,
    path_or_key: str,
    filename: str,
    sidecar: SidecarMetadata | None = None,
    cohort_only_nlp: bool = False,
) -> DocumentResult | None:
    """Process an HTML document through the shared NLP pipeline.

    This is the single source of truth for document processing logic,
    used by both the local and Ray build pipelines.

    Args:
        html: Raw HTML content (already decoded to str).
        path_or_key: Relative filesystem path or S3 key (stored in doc record).
        filename: Basename of the file (used for classification, filing date).
        sidecar: Optional metadata sidecar (company_name, cik, accession).
        cohort_only_nlp: If True, skip expensive NLP for non-cohort documents
            (section parsing, clause parsing, definitions, metadata extraction).
            Non-cohort docs still get classification and basic counts.

    Returns:
        A DocumentResult with all 7 record lists, or None on empty/short input.
    """
    # Step 1: Strip HTML for text length check
    text = strip_html(html)
    if not text or len(text) < 100:
        return None

    # Step 2: Normalize HTML
    normalized_text, _inverse_map = normalize_html(html)

    # Step 3: Content-addressed doc_id
    doc_id = compute_doc_id(normalized_text)

    # Step 4: Classification (runs for ALL documents)
    signals = extract_classification_signals(normalized_text, filename)
    doc_type, dt_confidence, _dt_reasons = classify_document_type(
        filename, signals,
    )
    market_segment, seg_confidence, _seg_reasons = classify_market_segment(signals)
    cohort = is_cohort_included(doc_type, dt_confidence, market_segment, seg_confidence)

    # Step 5: CIK + accession from path, optionally overridden by sidecar
    cik = extract_cik(path_or_key)
    accession = extract_accession(path_or_key)
    company_name = ""
    if sidecar is not None:
        if sidecar.cik:
            cik = sidecar.cik
        if sidecar.accession:
            accession = normalize_accession(sidecar.accession)
        company_name = sidecar.company_name

    # --- EARLY EXIT: skip expensive NLP for non-cohort documents ---
    if cohort_only_nlp and not cohort:
        doc_record: dict[str, Any] = {
            "doc_id": doc_id,
            "cik": cik,
            "accession": accession,
            "path": path_or_key,
            "borrower": company_name,
            "admin_agent": "",
            "facility_size_mm": None,
            "facility_confidence": "none",
            "closing_ebitda_mm": None,
            "ebitda_confidence": "none",
            "closing_date": None,
            "filing_date": normalize_date_value(extract_filing_date(filename)),
            "form_type": "",
            "template_family": "",
            "doc_type": doc_type,
            "doc_type_confidence": dt_confidence,
            "market_segment": market_segment,
            "segment_confidence": seg_confidence,
            "cohort_included": False,
            "word_count": signals.word_count,
            "section_count": 0,
            "clause_count": 0,
            "definition_count": 0,
            "text_length": len(normalized_text),
            "section_parser_mode": "",
            "section_fallback_used": False,
        }
        return DocumentResult(
            doc=doc_record,
            sections=[],
            clauses=[],
            definitions=[],
            section_texts=[],
            section_features=[],
            clause_features=[],
            articles=[],
        )

    # --- FULL NLP PIPELINE ---

    # Step 6: Parse outline (articles and sections)
    outline = DocOutline.from_text(normalized_text, filename=filename)
    all_sections: list[OutlineSection] = outline.sections
    section_parser_mode = "doc_outline"
    section_fallback_used = False

    if not all_sections:
        from agent.section_parser import find_sections

        all_sections = find_sections(normalized_text)  # type: ignore[assignment]
        if all_sections:
            section_parser_mode = "regex_fallback"
            section_fallback_used = True
        else:
            section_parser_mode = "none"

    # Step 6b: Build article records
    article_records: list[dict[str, Any]] = [
        {
            "doc_id": doc_id,
            "article_num": a.num,
            "label": a.label,
            "title": a.title,
            "concept": a.concept,
            "char_start": a.char_start,
            "char_end": a.char_end,
            "is_synthetic": a.is_synthetic,
        }
        for a in outline.articles
    ]

    # Step 7: Parse clauses per section
    all_clauses: list[tuple[str, ClauseNode]] = []
    for section in all_sections:
        section_text_slice = normalized_text[section.char_start : section.char_end]
        clauses = parse_clauses(
            section_text_slice,
            global_offset=section.char_start,
        )
        for clause in clauses:
            all_clauses.append((section.number, clause))

    # Clause fallback retry: if sections exist but clause extraction failed,
    # retry using the section parser's regex fallback boundaries.
    if all_sections and not all_clauses:
        from agent.section_parser import find_sections

        fallback_sections = find_sections(normalized_text)
        if fallback_sections:
            fallback_clauses: list[tuple[str, ClauseNode]] = []
            for section in fallback_sections:
                section_text_slice = normalized_text[
                    section.char_start : section.char_end
                ]
                clauses = parse_clauses(
                    section_text_slice,
                    global_offset=section.char_start,
                )
                for clause in clauses:
                    fallback_clauses.append((section.number, clause))
            if fallback_clauses:
                all_sections = fallback_sections  # type: ignore[assignment]
                all_clauses = fallback_clauses
                section_parser_mode = "regex_fallback"
                section_fallback_used = True

    # Step 8: Extract definitions
    definitions: list[DefinedTerm] = extract_definitions(normalized_text)

    # Step 9: Metadata extraction
    borrower_info = extract_borrower(normalized_text)
    borrower = str(borrower_info.get("borrower", "") or "")
    if not borrower:
        borrower = company_name

    admin_agent = extract_admin_agent(normalized_text)
    facility_sizes = extract_facility_sizes(normalized_text)
    facility_size_mm = facility_sizes.get("facility_size_mm") if facility_sizes else None
    facility_confidence = (
        facility_sizes.get("facility_confidence", "none") if facility_sizes else "none"
    )
    grower_data = extract_grower_baskets(normalized_text)
    closing_ebitda_mm = (
        grower_data.get("closing_ebitda_mm") if grower_data else None
    )
    ebitda_confidence = (
        grower_data.get("ebitda_confidence", "none") if grower_data else "none"
    )
    effective_date_info = extract_effective_date(normalized_text)
    effective_date = normalize_date_value(effective_date_info.get("closing_date"))
    filing_date = normalize_date_value(extract_filing_date(filename))

    # Step 10: Build document record
    doc_record = {
        "doc_id": doc_id,
        "cik": cik,
        "accession": accession,
        "path": path_or_key,
        "borrower": borrower,
        "admin_agent": admin_agent,
        "facility_size_mm": facility_size_mm,
        "facility_confidence": facility_confidence,
        "closing_ebitda_mm": closing_ebitda_mm,
        "ebitda_confidence": ebitda_confidence,
        "closing_date": effective_date,
        "filing_date": filing_date,
        "form_type": "",
        "template_family": "",
        "doc_type": doc_type,
        "doc_type_confidence": dt_confidence,
        "market_segment": market_segment,
        "segment_confidence": seg_confidence,
        "cohort_included": cohort,
        "word_count": signals.word_count,
        "section_count": len(all_sections),
        "clause_count": len(all_clauses),
        "definition_count": len(definitions),
        "text_length": len(normalized_text),
        "section_parser_mode": section_parser_mode,
        "section_fallback_used": section_fallback_used,
    }

    # Step 11: Build section records
    section_records: list[dict[str, Any]] = []
    section_text_records: list[dict[str, Any]] = []
    section_feature_records: list[dict[str, Any]] = []
    for section in all_sections:
        sec_text = normalized_text[section.char_start : section.char_end]
        section_records.append(
            {
                "doc_id": doc_id,
                "section_number": section.number,
                "heading": section.heading,
                "char_start": section.char_start,
                "char_end": section.char_end,
                "article_num": section.article_num,
                "word_count": section.word_count,
            }
        )
        section_text_records.append(
            {
                "doc_id": doc_id,
                "section_number": section.number,
                "text": sec_text,
            }
        )
        section_feature_records.append(
            build_section_feature(
                doc_id=doc_id,
                section_number=section.number,
                heading=section.heading,
                text=sec_text,
                char_start=section.char_start,
                char_end=section.char_end,
                article_num=section.article_num,
                word_count=section.word_count,
            )
        )

    # Step 12: Build clause records
    clause_records: list[dict[str, Any]] = []
    clause_feature_records: list[dict[str, Any]] = []
    for section_number, clause in all_clauses:
        clause_text = ""
        if 0 <= clause.span_start < clause.span_end <= len(normalized_text):
            clause_text = normalized_text[clause.span_start : clause.span_end]
        clause_records.append(
            {
                "doc_id": doc_id,
                "section_number": section_number,
                "clause_id": clause.id,
                "label": clause.label,
                "depth": clause.depth,
                "level_type": clause.level_type,
                "span_start": clause.span_start,
                "span_end": clause.span_end,
                "header_text": clause.header_text,
                "clause_text": clause_text,
                "parent_id": clause.parent_id,
                "is_structural": clause.is_structural_candidate,
                "parse_confidence": clause.parse_confidence,
            }
        )
        clause_feature_records.append(
            build_clause_feature(
                doc_id=doc_id,
                section_number=section_number,
                clause_id=clause.id,
                depth=clause.depth,
                level_type=clause.level_type,
                clause_text=clause_text,
                parse_confidence=clause.parse_confidence,
                is_structural=clause.is_structural_candidate,
            )
        )

    # Step 13: Build definition records
    def_records: list[dict[str, Any]] = []
    for defn in definitions:
        def_records.append(
            {
                "doc_id": doc_id,
                "term": defn.term,
                "definition_text": defn.definition_text,
                "char_start": defn.char_start,
                "char_end": defn.char_end,
                "pattern_engine": defn.pattern_engine,
                "confidence": defn.confidence,
                "definition_type": getattr(defn, "definition_type", "DIRECT"),
                "definition_types": json.dumps(
                    list(getattr(defn, "definition_types", ()))
                ),
                "type_confidence": getattr(defn, "type_confidence", 0.0),
                "type_signals": json.dumps(
                    list(getattr(defn, "type_signals", ()))
                ),
                "dependency_terms": json.dumps(
                    list(getattr(defn, "dependency_terms", ()))
                ),
            }
        )

    return DocumentResult(
        doc=doc_record,
        sections=section_records,
        clauses=clause_records,
        definitions=def_records,
        section_texts=section_text_records,
        section_features=section_feature_records,
        clause_features=clause_feature_records,
        articles=article_records,
    )
