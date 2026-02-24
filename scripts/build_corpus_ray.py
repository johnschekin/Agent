#!/usr/bin/env python3
"""Build a DuckDB corpus index from S3-hosted HTML documents using Ray.

Distributed pipeline that streams HTML directly from S3, processes each
document through the agent NLP library, and writes results incrementally
to DuckDB via a writer actor with bounded memory.

Supports:
  - AWS EC2 Ray cluster (ray up ray-cluster.yaml) or local mode
  - Checkpoint/resume after crash
  - S3 upload of finished DuckDB

Usage (local):
    python3 scripts/build_corpus_ray.py \
        --bucket edgar-pipeline-documents-216213517387 \
        --output corpus_index/corpus.duckdb \
        --local --limit 10 -v

Usage (cluster):
    ray submit ray-cluster.yaml scripts/build_corpus_ray.py -- \
        --bucket edgar-pipeline-documents-216213517387 \
        --output corpus_index/corpus.duckdb \
        --s3-upload s3://edgar-pipeline-documents-216213517387/corpus_index/corpus.duckdb
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import re
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ray

# ---------------------------------------------------------------------------
# Agent library imports (same as build_corpus_index.py)
# ---------------------------------------------------------------------------
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
)
from agent.parsing_types import OutlineSection
from agent.run_manifest import (
    build_manifest,
    generate_run_id,
    git_commit_hash,
    write_manifest,
)

# Dynamic imports for non-type-checked deps
_duckdb = importlib.import_module("duckdb")

try:
    import orjson

    def _dump_json(obj: object) -> bytes:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2)

    def _load_json(data: bytes) -> Any:
        return orjson.loads(data)
except ImportError:
    import json as _json

    def _dump_json(obj: object) -> bytes:  # type: ignore[misc]
        return _json.dumps(obj, indent=2, default=str).encode("utf-8")

    def _load_json(data: bytes) -> Any:  # type: ignore[misc]
        return _json.loads(data)

log = logging.getLogger("build_corpus_ray")

# ---------------------------------------------------------------------------
# Schema DDL (verbatim from build_corpus_index.py)
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS _schema_version (
    table_name VARCHAR PRIMARY KEY,
    version VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT current_timestamp
);

INSERT OR IGNORE INTO _schema_version VALUES ('corpus', '0.2.0', current_timestamp);

CREATE TABLE IF NOT EXISTS documents (
    doc_id VARCHAR PRIMARY KEY,
    cik VARCHAR,
    accession VARCHAR,
    path VARCHAR,
    borrower VARCHAR DEFAULT '',
    admin_agent VARCHAR DEFAULT '',
    facility_size_mm DOUBLE,
    closing_date DATE,
    filing_date DATE,
    form_type VARCHAR DEFAULT '',
    template_family VARCHAR DEFAULT '',
    doc_type VARCHAR DEFAULT 'other',
    doc_type_confidence VARCHAR DEFAULT 'low',
    market_segment VARCHAR DEFAULT 'uncertain',
    segment_confidence VARCHAR DEFAULT 'low',
    cohort_included BOOLEAN DEFAULT false,
    word_count INTEGER DEFAULT 0,
    section_count INTEGER DEFAULT 0,
    clause_count INTEGER DEFAULT 0,
    definition_count INTEGER DEFAULT 0,
    text_length INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sections (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    heading VARCHAR,
    char_start INTEGER,
    char_end INTEGER,
    article_num INTEGER,
    word_count INTEGER,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE IF NOT EXISTS clauses (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    clause_id VARCHAR NOT NULL,
    label VARCHAR,
    depth INTEGER,
    level_type VARCHAR,
    span_start INTEGER,
    span_end INTEGER,
    header_text VARCHAR,
    clause_text VARCHAR,
    parent_id VARCHAR DEFAULT '',
    is_structural BOOLEAN DEFAULT true,
    parse_confidence DOUBLE DEFAULT 0.0,
    PRIMARY KEY (doc_id, section_number, clause_id)
);

CREATE TABLE IF NOT EXISTS definitions (
    doc_id VARCHAR NOT NULL,
    term VARCHAR NOT NULL,
    definition_text VARCHAR,
    char_start INTEGER,
    char_end INTEGER,
    pattern_engine VARCHAR,
    confidence DOUBLE DEFAULT 0.0,
    definition_type VARCHAR DEFAULT 'DIRECT',
    definition_types VARCHAR,
    type_confidence DOUBLE DEFAULT 0.0,
    type_signals VARCHAR,
    dependency_terms VARCHAR
);

CREATE TABLE IF NOT EXISTS section_text (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    text VARCHAR,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE IF NOT EXISTS section_features (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    article_num INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    word_count INTEGER,
    char_count INTEGER,
    heading_lower VARCHAR,
    scope_label VARCHAR,
    scope_operator_count INTEGER,
    scope_permit_count INTEGER,
    scope_restrict_count INTEGER,
    scope_estimated_depth INTEGER,
    preemption_override_count INTEGER,
    preemption_yield_count INTEGER,
    preemption_estimated_depth INTEGER,
    preemption_has BOOLEAN,
    preemption_edge_count INTEGER,
    definition_types VARCHAR,
    definition_type_primary VARCHAR,
    definition_type_confidence DOUBLE,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE IF NOT EXISTS clause_features (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    clause_id VARCHAR NOT NULL,
    depth INTEGER,
    level_type VARCHAR,
    token_count INTEGER,
    char_count INTEGER,
    has_digits BOOLEAN,
    parse_confidence DOUBLE,
    is_structural BOOLEAN,
    PRIMARY KEY (doc_id, section_number, clause_id)
);
"""

# ---------------------------------------------------------------------------
# Regex helpers (from build_corpus_index.py)
# ---------------------------------------------------------------------------

_CIK_DIR_RE = re.compile(r"cik=(\d{10})")
_ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR_ONLY_RE = re.compile(r"^\d{4}$")


def _extract_cik(path_str: str) -> str:
    """Extract CIK from an S3 key containing cik=XXXXXXXXXX."""
    m = _CIK_DIR_RE.search(path_str)
    return m.group(1) if m else ""


def _extract_accession(path_str: str) -> str:
    """Extract accession number from S3 key."""
    stem = Path(path_str).stem
    m = _ACCESSION_RE.search(stem)
    if m:
        return m.group(1)
    m = _ACCESSION_RE.search(path_str)
    return m.group(1) if m else ""


def _normalize_date_value(value: Any) -> str | None:
    """Normalize metadata date values to YYYY-MM-DD for DuckDB DATE columns."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if _ISO_DATE_RE.match(raw):
        return raw
    if len(raw) >= 10 and _ISO_DATE_RE.match(raw[:10]):
        return raw[:10]
    if _YEAR_ONLY_RE.match(raw):
        return None
    return None


def _compute_doc_id(normalized_text: str) -> str:
    """Content-addressed doc_id: SHA-256 truncated to 16 hex chars."""
    h = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return h[:16]


def _meta_key_for_doc_key(doc_key: str) -> str | None:
    """Derive metadata S3 key from a document S3 key.

    documents/cik=X/acc_ex.htm -> metadata/cik=X/acc.meta.json
    """
    if not doc_key.startswith("documents/"):
        return None
    meta_key = doc_key.replace("documents/", "metadata/", 1)
    stem = Path(meta_key).stem
    acc_match = _ACCESSION_RE.search(stem)
    if acc_match:
        accession = acc_match.group(1)
        return str(Path(meta_key).with_name(f"{accession}.meta.json"))
    return str(Path(meta_key).with_suffix(".meta.json"))


# ---------------------------------------------------------------------------
# Parse anomaly helpers
# ---------------------------------------------------------------------------


def _derive_failure_signatures(
    *,
    section_count: int,
    clause_count: int,
    word_count: int,
    text_length: int,
    section_fallback_used: bool,
) -> list[str]:
    signatures: list[str] = []
    if section_count == 0:
        signatures.append("no_sections_detected")
        if word_count < 200:
            signatures.append("low_word_count")
        if text_length < 1000:
            signatures.append("short_text")
    if clause_count == 0:
        signatures.append("no_clauses_detected")
        if section_count > 0:
            signatures.append("sections_without_clause_nodes")
    if section_fallback_used:
        signatures.append("section_fallback_applied")
    if not signatures:
        signatures.append("none")
    return signatures


def _build_anomaly_row(
    doc_record: dict[str, Any],
    *,
    template_family_map: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    section_count = int(doc_record.get("section_count", 0) or 0)
    clause_count = int(doc_record.get("clause_count", 0) or 0)
    if section_count > 0 and clause_count > 0:
        return None

    doc_id = str(doc_record.get("doc_id", ""))
    if not doc_id:
        return None
    mapped_template = (
        template_family_map.get(doc_id)
        if template_family_map is not None
        else None
    )
    template_family = str(
        mapped_template
        if mapped_template
        else doc_record.get("template_family", "") or "unknown"
    )
    word_count = int(doc_record.get("word_count", 0) or 0)
    text_length = int(doc_record.get("text_length", 0) or 0)
    section_fallback_used = bool(doc_record.get("section_fallback_used", False))
    section_parser_mode = str(doc_record.get("section_parser_mode", "doc_outline"))
    signatures = _derive_failure_signatures(
        section_count=section_count,
        clause_count=clause_count,
        word_count=word_count,
        text_length=text_length,
        section_fallback_used=section_fallback_used,
    )
    return {
        "doc_id": doc_id,
        "path": str(doc_record.get("path", "")),
        "template_family": template_family,
        "section_count": section_count,
        "clause_count": clause_count,
        "definition_count": int(doc_record.get("definition_count", 0) or 0),
        "word_count": word_count,
        "text_length": text_length,
        "section_parser_mode": section_parser_mode,
        "section_fallback_used": section_fallback_used,
        "failure_signatures": signatures,
    }


def _write_anomaly_report(
    report_path: Path,
    anomaly_rows: list[dict[str, Any]],
    *,
    requested_docs: int,
    processed_docs: int,
    errors: int,
) -> Path:
    payload = {
        "schema_version": "parse_anomalies_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "requested_docs": requested_docs,
        "processed_docs": processed_docs,
        "errors": errors,
        "anomaly_count": len(anomaly_rows),
        "anomalies": sorted(
            anomaly_rows,
            key=lambda r: (str(r.get("template_family", "")), str(r.get("doc_id", ""))),
        ),
    }
    report_path.write_bytes(_dump_json(payload))
    return report_path


def _load_anomaly_rows_from_db(db_path: Path) -> list[dict[str, Any]]:
    """Load parse anomalies from DuckDB documents table."""
    conn = _duckdb.connect(str(db_path), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT doc_id, path, template_family, section_count, clause_count,
                   definition_count, word_count, text_length
            FROM documents
            WHERE section_count = 0 OR clause_count = 0
            ORDER BY template_family, doc_id
            """
        ).fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in rows:
        section_count = int(row[3] or 0)
        clause_count = int(row[4] or 0)
        word_count = int(row[6] or 0)
        text_length = int(row[7] or 0)
        out.append(
            {
                "doc_id": str(row[0] or ""),
                "path": str(row[1] or ""),
                "template_family": str(row[2] or "unknown"),
                "section_count": section_count,
                "clause_count": clause_count,
                "definition_count": int(row[5] or 0),
                "word_count": word_count,
                "text_length": text_length,
                "section_parser_mode": "unknown",
                "section_fallback_used": False,
                "failure_signatures": _derive_failure_signatures(
                    section_count=section_count,
                    clause_count=clause_count,
                    word_count=word_count,
                    text_length=text_length,
                    section_fallback_used=False,
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# S3 key listing
# ---------------------------------------------------------------------------


def _list_document_keys(
    bucket: str,
    region: str,
    profile: str | None = None,
) -> list[tuple[str, str | None]]:
    """List all HTML document keys in S3, returning (doc_key, meta_key) tuples."""
    import boto3

    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    html_extensions = {".htm", ".html"}
    doc_keys: list[str] = []

    log.info("Listing S3 keys in s3://%s/documents/ ...", bucket)
    for page in paginator.paginate(Bucket=bucket, Prefix="documents/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if Path(key).suffix.lower() in html_extensions:
                doc_keys.append(key)

    doc_keys.sort()
    log.info("Found %d document keys in S3", len(doc_keys))

    # Pair each doc key with its metadata key
    pairs: list[tuple[str, str | None]] = []
    for dk in doc_keys:
        mk = _meta_key_for_doc_key(dk)
        pairs.append((dk, mk))

    return pairs


# ---------------------------------------------------------------------------
# Checkpoint manager
# ---------------------------------------------------------------------------


class _CheckpointManager:
    """Track processed document keys for crash resume."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._processed: set[str] = set()
        self._errors: list[str] = []
        self._started_at: str = ""
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = _load_json(self._path.read_bytes())
            self._processed = set(data.get("processed_doc_keys", []))
            self._errors = list(data.get("errors", []))
            self._started_at = data.get("started_at", "")
            log.info(
                "Loaded checkpoint: %d processed, %d errors",
                len(self._processed),
                len(self._errors),
            )
        except Exception as exc:
            log.warning("Failed to load checkpoint %s: %s", self._path, exc)

    def is_processed(self, doc_key: str) -> bool:
        return doc_key in self._processed

    def mark_processed(self, doc_keys: list[str]) -> None:
        self._processed.update(doc_keys)

    def mark_error(self, doc_key: str) -> None:
        self._errors.append(doc_key)

    def save(self) -> None:
        if not self._started_at:
            self._started_at = datetime.now(UTC).isoformat()
        data = {
            "processed_doc_keys": sorted(self._processed),
            "errors": self._errors,
            "started_at": self._started_at,
            "last_updated": datetime.now(UTC).isoformat(),
            "total_processed": len(self._processed),
            "total_errors": len(self._errors),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(_dump_json(data))

    @property
    def processed_count(self) -> int:
        return len(self._processed)

    @property
    def error_count(self) -> int:
        return len(self._errors)


# ---------------------------------------------------------------------------
# Remote document processor
# ---------------------------------------------------------------------------


@ray.remote(num_cpus=1, max_retries=2)
def process_document(
    bucket: str,
    doc_key: str,
    meta_key: str | None,
    region: str,
) -> dict[str, Any] | None:
    """Process a single S3-hosted HTML document through the agent NLP pipeline.

    Creates a fresh boto3 client per invocation (not serializable across Ray).
    Returns a result dict or None on failure.
    """
    import boto3

    try:
        s3 = boto3.client("s3", region_name=region)

        # Step 1: Download HTML from S3
        resp = s3.get_object(Bucket=bucket, Key=doc_key)
        html_bytes = resp["Body"].read()

        # Try UTF-8, fall back to latin-1
        try:
            html = html_bytes.decode("utf-8")
        except UnicodeDecodeError:
            html = html_bytes.decode("latin-1")

        if not html or len(html) < 50:
            return None

        # Step 2: Strip HTML for text length check
        text = strip_html(html)
        if not text or len(text) < 100:
            return None

        # Step 3: Normalize HTML
        normalized_text, _inverse_map = normalize_html(html)

        # Step 4: Content-addressed doc_id
        doc_id = _compute_doc_id(normalized_text)

        # Step 5: Parse outline (articles and sections)
        filename = Path(doc_key).name
        outline = DocOutline.from_text(normalized_text, filename=filename)
        all_sections: list[OutlineSection] = outline.sections
        section_parser_mode = "doc_outline"
        section_fallback_used = False

        if not all_sections:
            from agent.section_parser import find_sections
            all_sections = find_sections(normalized_text)
            if all_sections:
                section_parser_mode = "regex_fallback"
                section_fallback_used = True
            else:
                section_parser_mode = "none"

        # Step 6: Parse clauses per section
        all_clauses: list[tuple[str, ClauseNode]] = []
        for section in all_sections:
            section_text_slice = normalized_text[section.char_start:section.char_end]
            clauses = parse_clauses(
                section_text_slice,
                global_offset=section.char_start,
            )
            for clause in clauses:
                all_clauses.append((section.number, clause))

        # Fallback: if sections exist but clause extraction failed, retry with
        # section parser fallback boundaries.
        if all_sections and not all_clauses:
            from agent.section_parser import find_sections
            fallback_sections = find_sections(normalized_text)
            if fallback_sections:
                fallback_clauses: list[tuple[str, ClauseNode]] = []
                for section in fallback_sections:
                    section_text_slice = normalized_text[section.char_start:section.char_end]
                    clauses = parse_clauses(
                        section_text_slice,
                        global_offset=section.char_start,
                    )
                    for clause in clauses:
                        fallback_clauses.append((section.number, clause))
                if fallback_clauses:
                    all_sections = fallback_sections
                    all_clauses = fallback_clauses
                    section_parser_mode = "regex_fallback"
                    section_fallback_used = True

        # Step 7: Extract definitions
        definitions: list[DefinedTerm] = extract_definitions(normalized_text)

        # Step 8: Metadata from S3 key path
        cik = _extract_cik(doc_key)
        accession = _extract_accession(doc_key)

        # Step 9: Load sidecar metadata from S3 if available
        sidecar_data: dict[str, Any] = {}
        if meta_key:
            try:
                meta_resp = s3.get_object(Bucket=bucket, Key=meta_key)
                meta_bytes = meta_resp["Body"].read()
                meta_obj = _load_json(meta_bytes)
                if isinstance(meta_obj, dict):
                    sidecar_data = meta_obj
                    if sidecar_data.get("cik"):
                        cik = str(sidecar_data["cik"])
                    if sidecar_data.get("accession"):
                        accession = str(sidecar_data["accession"])
            except Exception:
                pass  # Sidecar is optional

        # Step 10: Extract text metadata
        borrower = extract_borrower(normalized_text)
        if not borrower:
            borrower = str(sidecar_data.get("company_name", ""))
        admin_agent = extract_admin_agent(normalized_text)
        facility_sizes = extract_facility_sizes(normalized_text)
        facility_size_mm = facility_sizes.get("aggregate") if facility_sizes else None
        effective_date_info = extract_effective_date(normalized_text)
        effective_date = _normalize_date_value(effective_date_info.get("closing_date"))
        filing_date = _normalize_date_value(extract_filing_date(filename))

        # Step 11: Classification
        signals = extract_classification_signals(normalized_text, filename)
        doc_type, dt_confidence, _dt_reasons = classify_document_type(
            filename, signals,
        )
        market_segment, seg_confidence, _seg_reasons = classify_market_segment(signals)

        # Step 12: Cohort inclusion
        cohort_included = (
            doc_type == "credit_agreement"
            and market_segment == "leveraged"
            and dt_confidence in ("high", "medium")
            and seg_confidence in ("high", "medium")
        )

        # Build result dict
        doc_record = {
            "doc_id": doc_id,
            "cik": cik,
            "accession": accession,
            "path": doc_key,
            "borrower": borrower,
            "admin_agent": admin_agent,
            "facility_size_mm": facility_size_mm,
            "closing_date": effective_date,
            "filing_date": filing_date,
            "form_type": "",
            "template_family": "",
            "doc_type": doc_type,
            "doc_type_confidence": dt_confidence,
            "market_segment": market_segment,
            "segment_confidence": seg_confidence,
            "cohort_included": cohort_included,
            "word_count": signals.word_count,
            "section_count": len(all_sections),
            "clause_count": len(all_clauses),
            "definition_count": len(definitions),
            "text_length": len(normalized_text),
            "section_parser_mode": section_parser_mode,
            "section_fallback_used": section_fallback_used,
        }

        section_records = []
        section_text_records = []
        section_feature_records = []
        for section in all_sections:
            section_text = normalized_text[section.char_start:section.char_end]
            section_records.append({
                "doc_id": doc_id,
                "section_number": section.number,
                "heading": section.heading,
                "char_start": section.char_start,
                "char_end": section.char_end,
                "article_num": section.article_num,
                "word_count": section.word_count,
            })
            section_text_records.append({
                "doc_id": doc_id,
                "section_number": section.number,
                "text": section_text,
            })
            section_feature_records.append(
                build_section_feature(
                    doc_id=doc_id,
                    section_number=section.number,
                    heading=section.heading,
                    text=section_text,
                    char_start=section.char_start,
                    char_end=section.char_end,
                    article_num=section.article_num,
                    word_count=section.word_count,
                )
            )

        clause_records = []
        clause_feature_records = []
        for section_number, clause in all_clauses:
            clause_text = ""
            if 0 <= clause.span_start < clause.span_end <= len(normalized_text):
                clause_text = normalized_text[clause.span_start:clause.span_end]
            clause_records.append({
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
            })
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

        def_records = []
        for defn in definitions:
            def_records.append({
                "doc_id": doc_id,
                "term": defn.term,
                "definition_text": defn.definition_text,
                "char_start": defn.char_start,
                "char_end": defn.char_end,
                "pattern_engine": defn.pattern_engine,
                "confidence": defn.confidence,
                "definition_type": getattr(defn, "definition_type", "DIRECT"),
                "definition_types": json.dumps(list(getattr(defn, "definition_types", ()))),
                "type_confidence": getattr(defn, "type_confidence", 0.0),
                "type_signals": json.dumps(list(getattr(defn, "type_signals", ()))),
                "dependency_terms": json.dumps(list(getattr(defn, "dependency_terms", ()))),
            })

        return {
            "doc_key": doc_key,
            "doc": doc_record,
            "sections": section_records,
            "clauses": clause_records,
            "definitions": def_records,
            "section_texts": section_text_records,
            "section_features": section_feature_records,
            "clause_features": clause_feature_records,
        }

    except Exception as exc:
        print(
            f"  ERROR processing {doc_key}: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# DuckDB Writer Actor
# ---------------------------------------------------------------------------


@ray.remote(num_cpus=1)
class DuckDBWriterActor:
    """Stateful actor that accumulates results and batch-writes to DuckDB.

    Runs on the head node. Receives one result at a time, buffers them,
    and flushes to DuckDB every `batch_size` documents.
    """

    def __init__(
        self,
        output_path: str,
        batch_size: int,
        template_family_map: dict[str, str] | None = None,
        *,
        resume: bool = False,
    ) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        # On fresh build, remove existing DB; on resume, keep it
        if output.exists() and not resume:
            output.unlink()

        self._conn: Any = _duckdb.connect(output_path)
        # Create schema (IF NOT EXISTS is safe for resume)
        for stmt in _SCHEMA_DDL.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._conn.execute(stmt)

        self._batch_size = batch_size
        # On resume, load existing doc_ids to avoid duplicates
        self._seen_doc_ids: set[str] = set()
        if resume:
            try:
                rows = self._conn.sql("SELECT doc_id FROM documents").fetchall()
                self._seen_doc_ids = {r[0] for r in rows}
            except Exception:
                pass
        self._batch: list[dict[str, Any]] = []
        self._template_family_map = template_family_map or {}
        self._stats = {
            "docs": 0,
            "sections": 0,
            "clauses": 0,
            "definitions": 0,
            "section_texts": 0,
            "section_features": 0,
            "clause_features": 0,
        }

    def add_result(self, result: dict[str, Any]) -> None:
        """Add a processed document result to the batch buffer."""
        self._batch.append(result)
        if len(self._batch) >= self._batch_size:
            self._flush()

    def _flush(self) -> None:
        """Write buffered results to DuckDB."""
        if not self._batch:
            return

        all_docs: list[dict[str, Any]] = []
        all_sections: list[dict[str, Any]] = []
        all_clauses: list[dict[str, Any]] = []
        all_definitions: list[dict[str, Any]] = []
        all_section_texts: list[dict[str, Any]] = []
        all_section_features: list[dict[str, Any]] = []
        all_clause_features: list[dict[str, Any]] = []

        for result in self._batch:
            doc = result["doc"]
            doc_id = doc["doc_id"]

            # Handle doc_id collisions
            if doc_id in self._seen_doc_ids:
                suffix = 1
                while f"{doc_id}_{suffix}" in self._seen_doc_ids:
                    suffix += 1
                new_doc_id = f"{doc_id}_{suffix}"
                doc_id = new_doc_id
                doc["doc_id"] = doc_id
                for rec in result.get("sections", []):
                    rec["doc_id"] = doc_id
                for rec in result.get("clauses", []):
                    rec["doc_id"] = doc_id
                for rec in result.get("definitions", []):
                    rec["doc_id"] = doc_id
                for rec in result.get("section_texts", []):
                    rec["doc_id"] = doc_id
                for rec in result.get("section_features", []):
                    rec["doc_id"] = doc_id
                for rec in result.get("clause_features", []):
                    rec["doc_id"] = doc_id

            self._seen_doc_ids.add(doc_id)

            # Apply template family map
            if self._template_family_map:
                family = self._template_family_map.get(doc_id)
                if family:
                    doc["template_family"] = family

            all_docs.append(doc)
            all_sections.extend(result["sections"])
            all_clauses.extend(result["clauses"])
            all_definitions.extend(result["definitions"])
            all_section_texts.extend(result["section_texts"])
            all_section_features.extend(result.get("section_features", []))
            all_clause_features.extend(result.get("clause_features", []))

        # Deduplicate clauses by (doc_id, section_number, clause_id)
        seen_clause_keys: set[tuple[str, str, str]] = set()
        deduped_clauses: list[dict[str, Any]] = []
        for clause in all_clauses:
            key = (
                str(clause["doc_id"]),
                str(clause["section_number"]),
                str(clause["clause_id"]),
            )
            if key not in seen_clause_keys:
                seen_clause_keys.add(key)
                deduped_clauses.append(clause)
        all_clauses = deduped_clauses

        # Keep clause feature rows aligned with deduped clause keys.
        seen_clause_feature_keys: set[tuple[str, str, str]] = set()
        deduped_clause_features: list[dict[str, Any]] = []
        for feature in all_clause_features:
            key = (
                str(feature["doc_id"]),
                str(feature["section_number"]),
                str(feature["clause_id"]),
            )
            if key in seen_clause_keys and key not in seen_clause_feature_keys:
                seen_clause_feature_keys.add(key)
                deduped_clause_features.append(feature)
        all_clause_features = deduped_clause_features

        # Recompute per-doc clause counts from deduped clause payload.
        clause_count_by_doc: dict[str, int] = {}
        for clause in all_clauses:
            doc_id = str(clause["doc_id"])
            clause_count_by_doc[doc_id] = clause_count_by_doc.get(doc_id, 0) + 1
        for doc in all_docs:
            doc_id = str(doc["doc_id"])
            doc["clause_count"] = clause_count_by_doc.get(doc_id, 0)

        # Batch INSERT into each table
        if all_docs:
            self._conn.executemany(
                """INSERT INTO documents
                   (doc_id, cik, accession, path, borrower, admin_agent,
                    facility_size_mm, closing_date, filing_date, form_type,
                    template_family, doc_type, doc_type_confidence,
                    market_segment, segment_confidence, cohort_included,
                    word_count, section_count, clause_count,
                    definition_count, text_length)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        d["doc_id"], d["cik"], d["accession"], d["path"],
                        d["borrower"], d["admin_agent"], d["facility_size_mm"],
                        d["closing_date"], d["filing_date"], d["form_type"],
                        d["template_family"], d["doc_type"],
                        d["doc_type_confidence"], d["market_segment"],
                        d["segment_confidence"], d["cohort_included"],
                        d["word_count"], d["section_count"],
                        d["clause_count"], d["definition_count"],
                        d["text_length"],
                    )
                    for d in all_docs
                ],
            )

        if all_sections:
            self._conn.executemany(
                """INSERT INTO sections
                   (doc_id, section_number, heading, char_start, char_end,
                    article_num, word_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        s["doc_id"], s["section_number"], s["heading"],
                        s["char_start"], s["char_end"], s["article_num"],
                        s["word_count"],
                    )
                    for s in all_sections
                ],
            )

        if all_clauses:
            self._conn.executemany(
                """INSERT INTO clauses
                   (doc_id, section_number, clause_id, label, depth,
                    level_type, span_start, span_end, header_text, clause_text,
                    parent_id, is_structural, parse_confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        c["doc_id"], c["section_number"], c["clause_id"],
                        c["label"], c["depth"], c["level_type"],
                        c["span_start"], c["span_end"], c["header_text"],
                        c["clause_text"], c["parent_id"], c["is_structural"],
                        c["parse_confidence"],
                    )
                    for c in all_clauses
                ],
            )

        if all_definitions:
            self._conn.executemany(
                """INSERT INTO definitions
                   (doc_id, term, definition_text, char_start, char_end,
                    pattern_engine, confidence, definition_type, definition_types,
                    type_confidence, type_signals, dependency_terms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        d["doc_id"], d["term"], d["definition_text"],
                        d["char_start"], d["char_end"], d["pattern_engine"],
                        d["confidence"], d["definition_type"], d["definition_types"],
                        d["type_confidence"], d["type_signals"], d["dependency_terms"],
                    )
                    for d in all_definitions
                ],
            )

        if all_section_texts:
            self._conn.executemany(
                """INSERT INTO section_text
                   (doc_id, section_number, text)
                   VALUES (?, ?, ?)""",
                [
                    (st["doc_id"], st["section_number"], st["text"])
                    for st in all_section_texts
                ],
            )

        if all_section_features:
            self._conn.executemany(
                """INSERT INTO section_features
                   (doc_id, section_number, article_num, char_start, char_end,
                    word_count, char_count, heading_lower, scope_label,
                    scope_operator_count, scope_permit_count, scope_restrict_count,
                    scope_estimated_depth, preemption_override_count,
                    preemption_yield_count, preemption_estimated_depth,
                    preemption_has, preemption_edge_count, definition_types,
                    definition_type_primary, definition_type_confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        sf["doc_id"], sf["section_number"], sf["article_num"],
                        sf["char_start"], sf["char_end"], sf["word_count"],
                        sf["char_count"], sf["heading_lower"], sf["scope_label"],
                        sf["scope_operator_count"], sf["scope_permit_count"],
                        sf["scope_restrict_count"], sf["scope_estimated_depth"],
                        sf["preemption_override_count"], sf["preemption_yield_count"],
                        sf["preemption_estimated_depth"], sf["preemption_has"],
                        sf["preemption_edge_count"], sf["definition_types"],
                        sf["definition_type_primary"], sf["definition_type_confidence"],
                    )
                    for sf in all_section_features
                ],
            )

        if all_clause_features:
            self._conn.executemany(
                """INSERT INTO clause_features
                   (doc_id, section_number, clause_id, depth, level_type,
                    token_count, char_count, has_digits, parse_confidence, is_structural)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        cf["doc_id"], cf["section_number"], cf["clause_id"],
                        cf["depth"], cf["level_type"], cf["token_count"],
                        cf["char_count"], cf["has_digits"],
                        cf["parse_confidence"], cf["is_structural"],
                    )
                    for cf in all_clause_features
                ],
            )

        # Update stats
        self._stats["docs"] += len(all_docs)
        self._stats["sections"] += len(all_sections)
        self._stats["clauses"] += len(all_clauses)
        self._stats["definitions"] += len(all_definitions)
        self._stats["section_texts"] += len(all_section_texts)
        self._stats["section_features"] += len(all_section_features)
        self._stats["clause_features"] += len(all_clause_features)

        self._batch.clear()

    def finalize(self) -> dict[str, int]:
        """Flush remaining batch and close connection."""
        self._flush()
        self._conn.close()
        return self._stats.copy()

    def get_stats(self) -> dict[str, int]:
        """Return current write statistics."""
        return self._stats.copy()

    def get_batch_len(self) -> int:
        """Return current batch buffer length (for progress)."""
        return len(self._batch)


# ---------------------------------------------------------------------------
# S3 upload
# ---------------------------------------------------------------------------


def _upload_to_s3(
    local_path: str,
    s3_uri: str,
    region: str,
    profile: str | None = None,
) -> None:
    """Upload the finished DuckDB file to S3 with multipart transfer."""
    import boto3
    from boto3.s3.transfer import TransferConfig

    # Parse s3://bucket/key
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    parts = s3_uri[5:].split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid S3 URI (missing key): {s3_uri}")
    bucket, key = parts[0], parts[1]

    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")

    # Multipart config for large files
    config = TransferConfig(
        multipart_threshold=64 * 1024 * 1024,  # 64MB
        multipart_chunksize=64 * 1024 * 1024,
        max_concurrency=10,
    )

    file_size = Path(local_path).stat().st_size
    log.info(
        "Uploading %s (%.1f MB) to %s ...",
        local_path,
        file_size / (1024 * 1024),
        s3_uri,
    )

    s3.upload_file(local_path, bucket, key, Config=config)
    log.info("Upload complete: %s", s3_uri)


# ---------------------------------------------------------------------------
# Template family map loader
# ---------------------------------------------------------------------------


def _load_template_family_map(path: Path) -> dict[str, str]:
    """Load doc_id -> template_family mapping from classifier output JSON."""
    data = _load_json(path.read_bytes())
    if not isinstance(data, dict):
        return {}

    out: dict[str, str] = {}
    for doc_id, payload in data.items():
        if not isinstance(doc_id, str):
            continue
        if isinstance(payload, str):
            if payload:
                out[doc_id] = payload
            continue
        if isinstance(payload, dict):
            family = payload.get("template_family")
            if isinstance(family, str) and family:
                out[doc_id] = family
    return out


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def main() -> None:
    run_id = generate_run_id("ray_corpus_build")
    t0 = time.time()

    parser = argparse.ArgumentParser(
        description="Build DuckDB corpus index from S3 documents using Ray.",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="S3 bucket name containing documents/ prefix",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Local path for output DuckDB file",
    )
    parser.add_argument(
        "--s3-upload",
        default=None,
        help="Optional S3 URI to upload finished DuckDB (e.g. s3://bucket/key.duckdb)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Documents per DuckDB write batch (default: 100)",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Checkpoint file path for resume (default: {output}.checkpoint.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N documents (for testing)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local Ray (ray.init()) instead of connecting to a cluster",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional AWS profile name",
    )
    parser.add_argument(
        "--template-classifications",
        type=Path,
        default=None,
        help="Optional doc_id -> template_family JSON for labeling",
    )
    parser.add_argument(
        "--anomaly-output",
        type=Path,
        default=None,
        help=(
            "Optional path for parse anomaly report JSON. "
            "Default: <output>.anomalies.json"
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )
    parser.add_argument(
        "--writer-max-inflight",
        type=int,
        default=4000,
        help=(
            "Max pending writer actor calls before backpressure drains are applied "
            "(default: 4000)"
        ),
    )
    parser.add_argument(
        "--writer-drain-chunk",
        type=int,
        default=200,
        help="Writer call refs to await per backpressure drain (default: 200)",
    )
    parser.add_argument(
        "--writer-progress-interval",
        type=int,
        default=60,
        help="Seconds between writer-stage progress logs (default: 60)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file without confirmation",
    )
    args = parser.parse_args()
    if args.writer_max_inflight <= 0:
        parser.error("--writer-max-inflight must be > 0")
    if args.writer_drain_chunk <= 0:
        parser.error("--writer-drain-chunk must be > 0")
    if args.writer_progress_interval <= 0:
        parser.error("--writer-progress-interval must be > 0")

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # Suppress noisy boto3/botocore debug output
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)

    output_path: Path = args.output.resolve()
    anomaly_report_path: Path = (
        args.anomaly_output.resolve()
        if args.anomaly_output is not None
        else output_path.with_suffix(".anomalies.json")
    )
    anomaly_report_path.parent.mkdir(parents=True, exist_ok=True)
    bucket: str = args.bucket.strip().removeprefix("s3://").rstrip("/")

    # Checkpoint path
    checkpoint_path = args.checkpoint or Path(f"{output_path}.checkpoint.json")

    # Detect resume mode: checkpoint exists with processed docs
    is_resume = checkpoint_path.exists()

    # Check output file (skip prompt on resume — we want to keep the DB)
    if output_path.exists() and not args.force and not is_resume:
        response = input(
            f"Output file already exists: {output_path}\nOverwrite? [y/N] "
        )
        if response.strip().lower() not in ("y", "yes"):
            log.info("Aborted.")
            sys.exit(0)

    # Template family map
    template_family_map: dict[str, str] | None = None
    if args.template_classifications:
        tpath = args.template_classifications.resolve()
        if not tpath.exists():
            log.error("Template classifications file not found: %s", tpath)
            sys.exit(1)
        template_family_map = _load_template_family_map(tpath)
        log.info("Loaded %d template-family mappings", len(template_family_map))

    # -----------------------------------------------------------------------
    # Step 1: Initialize Ray
    # -----------------------------------------------------------------------
    if args.local:
        ray.init(ignore_reinit_error=True)
        log.info("Ray initialized in local mode")
    else:
        ray.init(address="auto")
        log.info("Connected to Ray cluster")

    cluster_resources = ray.cluster_resources()
    log.info(
        "Cluster resources: %d CPUs, %.1f GB memory",
        int(cluster_resources.get("CPU", 0)),
        cluster_resources.get("memory", 0) / (1024**3),
    )

    try:
        # -------------------------------------------------------------------
        # Step 2: List S3 document keys
        # -------------------------------------------------------------------
        all_pairs = _list_document_keys(bucket, args.region, args.profile)
        t_list_done = time.time()

        if args.limit and args.limit > 0:
            all_pairs = all_pairs[: args.limit]
            log.info("Limited to first %d documents", args.limit)

        if not all_pairs:
            log.error("No HTML documents found in s3://%s/documents/", bucket)
            sys.exit(1)

        # -------------------------------------------------------------------
        # Step 3: Load checkpoint and filter
        # -------------------------------------------------------------------
        ckpt = _CheckpointManager(checkpoint_path)
        work_pairs = [
            (dk, mk)
            for dk, mk in all_pairs
            if not ckpt.is_processed(dk)
        ]

        log.info(
            "Work queue: %d documents (%d already processed, %d remaining)",
            len(all_pairs),
            ckpt.processed_count,
            len(work_pairs),
        )

        if not work_pairs:
            if output_path.exists():
                log.info("All documents already processed. Writing no-op run manifest.")
                anomaly_rows = _load_anomaly_rows_from_db(output_path)
                _write_anomaly_report(
                    anomaly_report_path,
                    anomaly_rows,
                    requested_docs=len(all_pairs),
                    processed_docs=ckpt.processed_count,
                    errors=ckpt.error_count,
                )
                manifest = build_manifest(
                    run_id=run_id,
                    db_path=output_path,
                    input_source={
                        "mode": "ray_local" if args.local else "ray_cluster",
                        "bucket": bucket,
                        "region": args.region,
                        "limit": args.limit,
                        "resume": True,
                        "batch_size": args.batch_size,
                        "checkpoint_path": str(checkpoint_path),
                        "s3_upload": args.s3_upload,
                    },
                    timings_sec={
                        "list_keys": round(t_list_done - t0, 3),
                        "process": 0.0,
                        "finalize": 0.0,
                        "upload": 0.0,
                        "total": round(time.time() - t0, 3),
                    },
                    errors_count=ckpt.error_count,
                    stats={
                        "requested_docs": len(all_pairs),
                        "already_processed_docs": ckpt.processed_count,
                        "remaining_docs": 0,
                        "no_op": True,
                        "parse_anomaly_count": len(anomaly_rows),
                        "parse_anomaly_report": str(anomaly_report_path),
                    },
                    git_commit=git_commit_hash(search_from=Path(__file__).resolve().parents[1]),
                )
                manifest_path, versioned_manifest_path = write_manifest(
                    output_path,
                    manifest,
                )
                log.info("Run manifest: %s", manifest_path)
                log.info("Versioned manifest: %s", versioned_manifest_path)
                log.info(
                    "Parse anomalies: %d (report: %s)",
                    len(anomaly_rows),
                    anomaly_report_path,
                )
            else:
                log.info("All documents already processed. Nothing to do.")
            ray.shutdown()
            return

        # -------------------------------------------------------------------
        # Step 4: Create DuckDB writer actor
        # -------------------------------------------------------------------
        writer = DuckDBWriterActor.remote(  # type: ignore[attr-defined]
            str(output_path),
            args.batch_size,
            template_family_map,
            resume=is_resume,
        )

        # -------------------------------------------------------------------
        # Step 5: Submit tasks in waves + collect results
        # -------------------------------------------------------------------
        num_cpus = int(ray.cluster_resources().get("CPU", 4))
        wave_size = num_cpus * 8  # Keep 8x CPUs in flight for pipelining
        total = len(work_pairs)
        submitted = 0
        completed = 0
        errors = 0
        batch_keys: list[str] = []
        last_log_time = time.time()
        writer_log_time = time.time()
        writer_pending_refs: list[ray.ObjectRef] = []  # type: ignore[type-arg]
        writer_drain_total = 0
        writer_peak_pending = 0

        active_futures: list[ray.ObjectRef] = []  # type: ignore[type-arg]
        future_to_key: dict[ray.ObjectRef, str] = {}  # type: ignore[type-arg]
        pair_iter = iter(work_pairs)

        log.info(
            "Processing %d documents (wave_size=%d, cpus=%d)...",
            total, wave_size, num_cpus,
        )
        t_process_start = time.time()

        while submitted < total or active_futures:
            # Fill up to wave_size active tasks
            while len(active_futures) < wave_size and submitted < total:
                doc_key, meta_key = next(pair_iter)
                ref = process_document.remote(  # type: ignore[attr-defined]
                    bucket, doc_key, meta_key, args.region,
                )
                active_futures.append(ref)
                future_to_key[ref] = doc_key
                submitted += 1

            if not active_futures:
                break

            # Wait for a batch of results (up to 20 at a time)
            num_ready = min(20, len(active_futures))
            done, active_futures = ray.wait(
                active_futures, num_returns=num_ready, timeout=60,
            )

            for ref in done:
                doc_key = future_to_key.pop(ref)
                try:
                    result = ray.get(ref)
                except Exception as exc:
                    log.warning("Task failed for %s: %s", doc_key, exc)
                    ckpt.mark_error(doc_key)
                    errors += 1
                    completed += 1
                    continue

                if result is None:
                    ckpt.mark_error(doc_key)
                    errors += 1
                else:
                    # Bounded writer queue: submit async, then apply explicit backpressure.
                    writer_ref = writer.add_result.remote(result)  # type: ignore[union-attr]
                    writer_pending_refs.append(writer_ref)
                    if len(writer_pending_refs) > writer_peak_pending:
                        writer_peak_pending = len(writer_pending_refs)
                    if len(writer_pending_refs) >= args.writer_max_inflight:
                        drain_n = min(args.writer_drain_chunk, len(writer_pending_refs))
                        drained, writer_pending_refs = ray.wait(
                            writer_pending_refs,
                            num_returns=drain_n,
                            timeout=None,
                        )
                        ray.get(drained)
                        writer_drain_total += len(drained)
                    batch_keys.append(doc_key)

                completed += 1

            # Save checkpoint every batch_size docs
            if len(batch_keys) >= args.batch_size:
                ckpt.mark_processed(batch_keys)
                ckpt.save()
                batch_keys.clear()

            # Progress logging every 100 docs or 30 seconds
            now = time.time()
            if completed % 100 == 0 or (now - last_log_time) > 30:
                elapsed = now - last_log_time
                pct = 100.0 * completed / total
                eta_sec = (total - completed) / max(1, completed / max(1, elapsed))
                log.info(
                    (
                        "Progress: %d/%d (%.1f%%) — %d errors — ETA %.0fm "
                        "(writer_pending=%d drained=%d)"
                    ),
                    completed, total, pct, errors, eta_sec / 60,
                    len(writer_pending_refs), writer_drain_total,
                )
                last_log_time = now
            if (now - writer_log_time) >= args.writer_progress_interval:
                writer_stats = ray.get(writer.get_stats.remote())  # type: ignore[union-attr]
                writer_batch_len = ray.get(writer.get_batch_len.remote())  # type: ignore[union-attr]
                log.info(
                    (
                        "Writer stage: docs_written=%d sections=%d clauses=%d "
                        "definitions=%d actor_batch=%d pending_calls=%d"
                    ),
                    int(writer_stats.get("docs", 0)),
                    int(writer_stats.get("sections", 0)),
                    int(writer_stats.get("clauses", 0)),
                    int(writer_stats.get("definitions", 0)),
                    int(writer_batch_len),
                    len(writer_pending_refs),
                )
                writer_log_time = now

        # Final checkpoint save
        if batch_keys:
            ckpt.mark_processed(batch_keys)
            ckpt.save()

        # Ensure writer actor queue is fully drained before finalize.
        if writer_pending_refs:
            log.info("Draining %d pending writer calls...", len(writer_pending_refs))
            while writer_pending_refs:
                drain_n = min(args.writer_drain_chunk, len(writer_pending_refs))
                drained, writer_pending_refs = ray.wait(
                    writer_pending_refs,
                    num_returns=drain_n,
                    timeout=None,
                )
                ray.get(drained)
                writer_drain_total += len(drained)
                if writer_drain_total % 1000 == 0 or not writer_pending_refs:
                    log.info(
                        "Writer drain progress: drained=%d pending=%d",
                        writer_drain_total,
                        len(writer_pending_refs),
                    )

        # -------------------------------------------------------------------
        # Step 7: Finalize writer
        # -------------------------------------------------------------------
        t_finalize_start = time.time()
        stats = ray.get(writer.finalize.remote())  # type: ignore[union-attr]
        t_finalize_done = time.time()
        log.info(
            "DuckDB finalized: %d docs, %d sections, %d clauses, %d definitions",
            stats["docs"],
            stats["sections"],
            stats["clauses"],
            stats["definitions"],
        )

        # -------------------------------------------------------------------
        # Step 8: Upload to S3 if requested
        # -------------------------------------------------------------------
        if args.s3_upload:
            t_upload_start = time.time()
            _upload_to_s3(
                str(output_path),
                args.s3_upload,
                args.region,
                args.profile,
            )
            t_upload_done = time.time()
        else:
            t_upload_start = t_finalize_done
            t_upload_done = t_finalize_done

        anomaly_rows = _load_anomaly_rows_from_db(output_path)
        _write_anomaly_report(
            anomaly_report_path,
            anomaly_rows,
            requested_docs=len(all_pairs),
            processed_docs=int(stats.get("docs", 0)),
            errors=errors,
        )

        manifest = build_manifest(
            run_id=run_id,
            db_path=output_path,
            input_source={
                "mode": "ray_local" if args.local else "ray_cluster",
                "bucket": bucket,
                "region": args.region,
                "limit": args.limit,
                "resume": is_resume,
                "batch_size": args.batch_size,
                "writer_max_inflight": args.writer_max_inflight,
                "writer_drain_chunk": args.writer_drain_chunk,
                "checkpoint_path": str(checkpoint_path),
                "s3_upload": args.s3_upload,
            },
            timings_sec={
                "list_keys": round(t_list_done - t0, 3),
                "process": round(t_finalize_start - t_process_start, 3),
                "finalize": round(t_finalize_done - t_finalize_start, 3),
                "upload": round(t_upload_done - t_upload_start, 3),
                "total": round(t_upload_done - t0, 3),
            },
            errors_count=errors,
            stats={
                "requested_docs": len(all_pairs),
                "already_processed_docs": ckpt.processed_count,
                "remaining_docs_at_start": len(work_pairs),
                "writer_stats": stats,
                "writer_drain_total": writer_drain_total,
                "writer_peak_pending": writer_peak_pending,
                "parse_anomaly_count": len(anomaly_rows),
                "parse_anomaly_report": str(anomaly_report_path),
            },
            git_commit=git_commit_hash(search_from=Path(__file__).resolve().parents[1]),
        )
        manifest_path, versioned_manifest_path = write_manifest(output_path, manifest)
        log.info("Run manifest: %s", manifest_path)
        log.info("Versioned manifest: %s", versioned_manifest_path)

        # -------------------------------------------------------------------
        # Summary
        # -------------------------------------------------------------------
        print(
            f"\nCorpus build complete:\n"
            f"  Documents: {stats['docs']}\n"
            f"  Sections:  {stats['sections']}\n"
            f"  Clauses:   {stats['clauses']}\n"
            f"  Definitions: {stats['definitions']}\n"
            f"  Section features: {stats.get('section_features', 0)}\n"
            f"  Clause features: {stats.get('clause_features', 0)}\n"
            f"  Errors:    {errors}\n"
            f"  Output:    {output_path}\n"
            f"  Parse anomalies: {len(anomaly_rows)} ({anomaly_report_path})\n"
            f"  Manifest:  {manifest_path}\n",
            file=sys.stderr,
        )

    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
