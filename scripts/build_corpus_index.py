#!/usr/bin/env python3
"""Build a DuckDB corpus index from HTML credit agreement documents.

Reads HTML credit agreement files from a corpus directory, processes each
one through the agent library (HTML normalization, section parsing, clause
parsing, definition extraction), and writes the results to a DuckDB
database file.

Supports full rebuild, incremental rebuild (``--incremental``), and
table-specific rebuild (``--tables``).  Batched DuckDB writes with
explicit transactions keep peak memory low and provide crash safety.

Usage:
    python3 scripts/build_corpus_index.py \
        --corpus-dir corpus/ \
        --output corpus_index/corpus.duckdb \
        --workers 4

    # Incremental (only re-process changed files):
    python3 scripts/build_corpus_index.py \
        --corpus-dir corpus/ \
        --output corpus_index/corpus.duckdb \
        --incremental --force

    # Table-specific (only rebuild sections + dependents):
    python3 scripts/build_corpus_index.py \
        --corpus-dir corpus/ \
        --output corpus_index/corpus.duckdb \
        --tables sections --force
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import sys
import time
import traceback
from multiprocessing import Pool
from pathlib import Path
from typing import Any

try:
    import resource as _resource_mod
except ImportError:  # Windows
    _resource_mod = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Agent library imports
# ---------------------------------------------------------------------------
from agent.clause_parser import ClauseNode, parse_clauses
from agent.definitions import extract_definitions
from agent.doc_parser import DocOutline
from agent.document_processor import (
    SidecarMetadata,
    dedup_by_cik,
    extract_accession,
    process_document_text,
)
from agent.html_utils import normalize_html, read_file
from agent.io_utils import load_json
from agent.materialized_features import build_clause_feature, build_section_feature
from agent.parsing_types import OutlineSection
from agent.run_manifest import (
    build_manifest,
    generate_run_id,
    git_commit_hash,
    write_manifest,
)

# DuckDB: dynamic import for pyright compatibility
_duckdb = importlib.import_module("duckdb")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """\
CREATE TABLE _schema_version (
    table_name VARCHAR PRIMARY KEY,
    version VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT current_timestamp
);

INSERT INTO _schema_version VALUES ('corpus', '0.2.0', current_timestamp);

CREATE TABLE documents (
    doc_id VARCHAR PRIMARY KEY,
    cik VARCHAR,
    accession VARCHAR,
    path VARCHAR,
    borrower VARCHAR DEFAULT '',
    admin_agent VARCHAR DEFAULT '',
    facility_size_mm DOUBLE,
    facility_confidence VARCHAR DEFAULT 'none',
    closing_ebitda_mm DOUBLE,
    ebitda_confidence VARCHAR DEFAULT 'none',
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
    text_length INTEGER DEFAULT 0,
    section_parser_mode VARCHAR DEFAULT '',
    section_fallback_used BOOLEAN DEFAULT false
);

CREATE TABLE sections (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    heading VARCHAR,
    char_start INTEGER,
    char_end INTEGER,
    article_num INTEGER,
    word_count INTEGER,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE clauses (
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

CREATE TABLE definitions (
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

CREATE TABLE section_text (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    text VARCHAR,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE section_features (
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

CREATE TABLE clause_features (
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
# Note: CIK/accession extraction, date normalization, and doc_id computation
# are now in agent.document_processor (imported above).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Metadata sidecar matching
# ---------------------------------------------------------------------------


def _find_meta_sidecar(file_path: Path, corpus_dir: Path) -> Path | None:
    """Find the matching .meta.json sidecar for a document file.

    If the corpus has structure:
        corpus/documents/cik=.../accession_exhibit.htm
    Try to find:
        corpus/metadata/cik=.../accession.meta.json
    """
    try:
        rel = file_path.relative_to(corpus_dir)
    except ValueError:
        return None

    parts = list(rel.parts)

    # Check if the first directory component is "documents"
    if not parts or parts[0] != "documents":
        return None

    # Replace "documents" with "metadata"
    parts[0] = "metadata"

    # Change the filename: extract accession and make it {accession}.meta.json
    # Try both dashed and undashed forms since sidecar files may use either.
    accession = extract_accession(str(file_path))
    if accession:
        # Try dashed form first (canonical)
        parts[-1] = f"{accession}.meta.json"
        meta_path = corpus_dir / Path(*parts)
        if meta_path.exists():
            return meta_path
        # Try undashed form (common in EDGAR sidecars)
        undashed = accession.replace("-", "")
        parts[-1] = f"{undashed}.meta.json"
        meta_path = corpus_dir / Path(*parts)
        if meta_path.exists():
            return meta_path
        return None

    # Fallback: just replace the extension
    stem = Path(parts[-1]).stem
    parts[-1] = f"{stem}.meta.json"
    meta_path = corpus_dir / Path(*parts)
    if meta_path.exists():
        return meta_path
    return None


def _load_sidecar_metadata(meta_path: Path) -> dict[str, Any]:
    """Load and return relevant fields from a .meta.json sidecar."""
    try:
        data = load_json(meta_path)
        if not isinstance(data, dict):
            return {}
        return {
            "company_name": data.get("company_name", ""),
            "cik": data.get("cik", ""),
            "accession": data.get("accession", ""),
            "file_size": data.get("file_size", None),
        }
    except Exception:
        return {}


def _load_template_family_map(path: Path) -> dict[str, str]:
    """Load doc_id -> template_family mapping from classifier output JSON."""
    data = load_json(path)
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
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requested_docs": requested_docs,
        "processed_docs": processed_docs,
        "errors": errors,
        "anomaly_count": len(anomaly_rows),
        "anomalies": anomaly_rows,
    }
    report_path.write_text(json.dumps(payload, indent=2))
    return report_path


# ---------------------------------------------------------------------------
# Single-document processing
# ---------------------------------------------------------------------------


def _process_one_doc(
    args: tuple[Path, Path, int, int],
) -> dict[str, Any] | None:
    """Process a single HTML document and return extracted data.

    Thin wrapper around :func:`agent.document_processor.process_document_text`
    that handles local filesystem I/O and sidecar loading.

    Args is a tuple of (file_path, corpus_dir, file_index, total_files).
    Returns a dict with keys: doc, sections, clauses, definitions, section_texts,
    section_features, clause_features.  Returns None on failure.
    """
    file_path, corpus_dir, _file_index, _total_files = args

    try:
        # Read file (encoding-safe)
        html = read_file(file_path)
        if not html:
            print(
                f"  SKIP {file_path.name}: empty or unreadable",
                file=sys.stderr,
            )
            return None

        # Compute relative path for storage
        try:
            rel_path = str(file_path.relative_to(corpus_dir))
        except ValueError:
            rel_path = str(file_path)

        # Load sidecar metadata if present
        sidecar: SidecarMetadata | None = None
        meta_path = _find_meta_sidecar(file_path, corpus_dir)
        if meta_path is not None:
            sidecar_data = _load_sidecar_metadata(meta_path)
            sidecar = SidecarMetadata(
                company_name=str(sidecar_data.get("company_name", "")),
                cik=str(sidecar_data.get("cik", "")),
                accession=str(sidecar_data.get("accession", "")),
            )

        # Delegate to shared NLP pipeline
        result = process_document_text(
            html=html,
            path_or_key=rel_path,
            filename=file_path.name,
            sidecar=sidecar,
            cohort_only_nlp=False,
        )
        return result.to_dict() if result is not None else None

    except Exception as exc:
        print(
            f"  ERROR processing {file_path.name}: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _discover_html_files(corpus_dir: Path, limit: int | None = None) -> list[Path]:
    """Discover all HTML files in corpus_dir recursively, sorted for determinism."""
    extensions = {".htm", ".html"}
    files: list[Path] = []
    for f in sorted(corpus_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in extensions:
            files.append(f)
    if limit is not None and limit > 0:
        files = files[:limit]
    return files


def _dedup_by_cik_paths(
    files: list[Path],
    *,
    verbose: bool = False,
) -> list[Path]:
    """Keep only the most recent file per CIK directory (Path wrapper).

    Delegates to :func:`agent.document_processor.dedup_by_cik` after converting
    Path objects to strings, then converts back.
    """
    str_keys = [str(f) for f in files]
    kept_strs = dedup_by_cik(str_keys, verbose=verbose)
    kept_set = set(kept_strs)
    return [f for f in files if str(f) in kept_set]


# ---------------------------------------------------------------------------
# Progress reporter (Step 2)
# ---------------------------------------------------------------------------


def _get_rss_mb() -> float | None:
    """Return current process RSS in MB, or None if unavailable."""
    if _resource_mod is None:
        return None
    try:
        usage = _resource_mod.getrusage(_resource_mod.RUSAGE_SELF)
        rss = usage.ru_maxrss
        # macOS returns bytes; Linux returns kilobytes
        if platform.system() == "Darwin":
            return rss / (1024 * 1024)
        return rss / 1024
    except Exception:
        return None


class _ProgressReporter:
    """Lightweight progress reporter for long-running builds."""

    def __init__(self, total: int, *, interval_sec: float = 5.0) -> None:
        self._total = total
        self._interval_sec = interval_sec
        self._count = 0
        self._errors = 0
        self._start = time.monotonic()
        self._last_report = 0.0

    def tick(self, *, error: bool = False) -> None:
        self._count += 1
        if error:
            self._errors += 1
        now = time.monotonic()
        if now - self._last_report >= self._interval_sec:
            self._print_line()
            self._last_report = now

    def finish(self) -> None:
        self._print_line()

    def _print_line(self) -> None:
        elapsed = time.monotonic() - self._start
        rate = self._count / max(0.01, elapsed)
        remaining = self._total - self._count
        eta_sec = remaining / max(0.01, rate)
        pct = 100.0 * self._count / max(1, self._total)
        mem = _get_rss_mb()
        mem_str = f" | mem {mem:.0f}MB" if mem is not None else ""
        eta_str = f"{eta_sec / 60:.1f}m" if eta_sec > 60 else f"{eta_sec:.0f}s"
        print(
            f"[{self._count}/{self._total}] {pct:.1f}% | "
            f"{rate:.1f} docs/sec | ETA {eta_str} | "
            f"{self._errors} errors{mem_str}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Run stats accumulator (Step 3)
# ---------------------------------------------------------------------------


class _RunStats:
    """Incremental counters to replace post-hoc iteration over results."""

    def __init__(self) -> None:
        self.processed_docs: int = 0
        self.total_sections: int = 0
        self.total_clauses: int = 0
        self.total_definitions: int = 0
        self.total_section_features: int = 0
        self.total_clause_features: int = 0
        self.cohort_count: int = 0
        self.doc_type_counts: dict[str, int] = {}
        self.segment_counts: dict[str, int] = {}

    def accumulate(self, result: dict[str, Any]) -> None:
        self.processed_docs += 1
        self.total_sections += len(result.get("sections", []))
        self.total_clauses += len(result.get("clauses", []))
        self.total_definitions += len(result.get("definitions", []))
        self.total_section_features += len(result.get("section_features", []))
        self.total_clause_features += len(result.get("clause_features", []))
        doc = result["doc"]
        if doc.get("cohort_included"):
            self.cohort_count += 1
        dt = doc.get("doc_type", "other")
        self.doc_type_counts[dt] = self.doc_type_counts.get(dt, 0) + 1
        if dt == "credit_agreement":
            seg = doc.get("market_segment", "uncertain")
            self.segment_counts[seg] = self.segment_counts.get(seg, 0) + 1


# ---------------------------------------------------------------------------
# DuckDB batched writer (Step 3)
# ---------------------------------------------------------------------------


def _init_db(output_path: Path) -> Any:
    """Create a DuckDB file with schema, return open connection."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    conn: Any = _duckdb.connect(str(output_path))
    for stmt in _SCHEMA_DDL.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    return conn


def _execute_inserts(conn: Any, table_data: dict[str, list[tuple[Any, ...]]]) -> None:
    """Run all executemany calls for the 7 data tables."""
    docs = table_data.get("documents", [])
    if docs:
        conn.executemany(
            """INSERT INTO documents
               (doc_id, cik, accession, path, borrower, admin_agent,
                facility_size_mm, facility_confidence,
                closing_ebitda_mm, ebitda_confidence,
                closing_date, filing_date, form_type,
                template_family, doc_type, doc_type_confidence,
                market_segment, segment_confidence, cohort_included,
                word_count, section_count, clause_count,
                definition_count, text_length,
                section_parser_mode, section_fallback_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            docs,
        )
    sections = table_data.get("sections", [])
    if sections:
        conn.executemany(
            """INSERT INTO sections
               (doc_id, section_number, heading, char_start, char_end,
                article_num, word_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            sections,
        )
    clauses = table_data.get("clauses", [])
    if clauses:
        conn.executemany(
            """INSERT INTO clauses
               (doc_id, section_number, clause_id, label, depth,
                level_type, span_start, span_end, header_text, clause_text,
                parent_id, is_structural, parse_confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            clauses,
        )
    defs = table_data.get("definitions", [])
    if defs:
        conn.executemany(
            """INSERT INTO definitions
               (doc_id, term, definition_text, char_start, char_end,
                pattern_engine, confidence, definition_type, definition_types,
                type_confidence, type_signals, dependency_terms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            defs,
        )
    section_texts = table_data.get("section_text", [])
    if section_texts:
        conn.executemany(
            """INSERT INTO section_text
               (doc_id, section_number, text)
               VALUES (?, ?, ?)""",
            section_texts,
        )
    section_features = table_data.get("section_features", [])
    if section_features:
        conn.executemany(
            """INSERT INTO section_features
               (doc_id, section_number, article_num, char_start, char_end,
                word_count, char_count, heading_lower, scope_label,
                scope_operator_count, scope_permit_count, scope_restrict_count,
                scope_estimated_depth, preemption_override_count,
                preemption_yield_count, preemption_estimated_depth,
                preemption_has, preemption_edge_count, definition_types,
                definition_type_primary, definition_type_confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            section_features,
        )
    clause_features = table_data.get("clause_features", [])
    if clause_features:
        conn.executemany(
            """INSERT INTO clause_features
               (doc_id, section_number, clause_id, depth, level_type,
                token_count, char_count, has_digits, parse_confidence, is_structural)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            clause_features,
        )


def _prepare_batch_tuples(
    results: list[dict[str, Any]],
    seen_doc_ids: set[str],
    template_family_map: dict[str, str] | None,
    verbose: bool,
) -> dict[str, list[tuple[Any, ...]]]:
    """Prepare insert-ready tuples from a batch of result dicts.

    Handles doc_id collision resolution, template family override,
    clause deduplication, and clause count recomputation.
    """
    all_docs: list[dict[str, Any]] = []
    all_sections: list[dict[str, Any]] = []
    all_clauses: list[dict[str, Any]] = []
    all_definitions: list[dict[str, Any]] = []
    all_section_texts: list[dict[str, Any]] = []
    all_section_features: list[dict[str, Any]] = []
    all_clause_features: list[dict[str, Any]] = []

    for result in results:
        doc = result["doc"]
        doc_id = doc["doc_id"]

        # Handle doc_id collisions
        if doc_id in seen_doc_ids:
            suffix = 1
            while f"{doc_id}_{suffix}" in seen_doc_ids:
                suffix += 1
            new_doc_id = f"{doc_id}_{suffix}"
            if verbose:
                print(
                    f"  WARN: doc_id collision for {doc['path']}, "
                    f"reassigned {doc_id} -> {new_doc_id}",
                    file=sys.stderr,
                )
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

        seen_doc_ids.add(doc_id)

        if template_family_map:
            family = template_family_map.get(doc_id)
            if family:
                doc["template_family"] = family

        all_docs.append(doc)
        all_sections.extend(result.get("sections", []))
        all_clauses.extend(result.get("clauses", []))
        all_definitions.extend(result.get("definitions", []))
        all_section_texts.extend(result.get("section_texts", []))
        all_section_features.extend(result.get("section_features", []))
        all_clause_features.extend(result.get("clause_features", []))

    # Deduplicate clauses
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

    # Align clause_features
    seen_cf_keys: set[tuple[str, str, str]] = set()
    deduped_cf: list[dict[str, Any]] = []
    for feature in all_clause_features:
        key = (
            str(feature["doc_id"]),
            str(feature["section_number"]),
            str(feature["clause_id"]),
        )
        if key in seen_clause_keys and key not in seen_cf_keys:
            seen_cf_keys.add(key)
            deduped_cf.append(feature)
    all_clause_features = deduped_cf

    # Recompute clause counts
    clause_count_by_doc: dict[str, int] = {}
    for clause in all_clauses:
        did = str(clause["doc_id"])
        clause_count_by_doc[did] = clause_count_by_doc.get(did, 0) + 1
    for doc in all_docs:
        did = str(doc["doc_id"])
        doc["clause_count"] = clause_count_by_doc.get(did, 0)

    # Convert to tuples
    doc_tuples = [
        (
            d["doc_id"], d["cik"], d["accession"], d["path"],
            d["borrower"], d["admin_agent"], d["facility_size_mm"],
            d["facility_confidence"],
            d["closing_ebitda_mm"], d["ebitda_confidence"],
            d["closing_date"], d["filing_date"], d["form_type"],
            d["template_family"], d["doc_type"],
            d["doc_type_confidence"], d["market_segment"],
            d["segment_confidence"], d["cohort_included"],
            d["word_count"], d["section_count"],
            d["clause_count"], d["definition_count"],
            d["text_length"],
            d.get("section_parser_mode", ""),
            d.get("section_fallback_used", False),
        )
        for d in all_docs
    ]
    section_tuples = [
        (
            s["doc_id"], s["section_number"], s["heading"],
            s["char_start"], s["char_end"], s["article_num"],
            s["word_count"],
        )
        for s in all_sections
    ]
    clause_tuples = [
        (
            c["doc_id"], c["section_number"], c["clause_id"],
            c["label"], c["depth"], c["level_type"],
            c["span_start"], c["span_end"], c["header_text"],
            c["clause_text"], c["parent_id"], c["is_structural"],
            c["parse_confidence"],
        )
        for c in all_clauses
    ]
    def_tuples = [
        (
            d["doc_id"], d["term"], d["definition_text"],
            d["char_start"], d["char_end"], d["pattern_engine"],
            d["confidence"], d["definition_type"], d["definition_types"],
            d["type_confidence"], d["type_signals"], d["dependency_terms"],
        )
        for d in all_definitions
    ]
    st_tuples = [
        (st["doc_id"], st["section_number"], st["text"])
        for st in all_section_texts
    ]
    sf_tuples = [
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
    ]
    cf_tuples = [
        (
            cf["doc_id"], cf["section_number"], cf["clause_id"],
            cf["depth"], cf["level_type"], cf["token_count"],
            cf["char_count"], cf["has_digits"],
            cf["parse_confidence"], cf["is_structural"],
        )
        for cf in all_clause_features
    ]

    return {
        "documents": doc_tuples,
        "sections": section_tuples,
        "clauses": clause_tuples,
        "definitions": def_tuples,
        "section_text": st_tuples,
        "section_features": sf_tuples,
        "clause_features": cf_tuples,
    }


def _write_batch(
    conn: Any,
    results: list[dict[str, Any]],
    seen_doc_ids: set[str],
    template_family_map: dict[str, str] | None,
    verbose: bool,
) -> None:
    """Write one batch of results to DuckDB inside a transaction."""
    table_data = _prepare_batch_tuples(
        results, seen_doc_ids, template_family_map, verbose,
    )
    conn.execute("BEGIN")
    try:
        _execute_inserts(conn, table_data)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        # Fallback: single-row inserts for the failed batch
        _single_row_fallback(conn, table_data, verbose)


def _single_row_fallback(
    conn: Any,
    table_data: dict[str, list[tuple[Any, ...]]],
    verbose: bool,
) -> None:
    """Insert rows one at a time when a batch executemany fails."""
    for table_name, rows in table_data.items():
        if not rows:
            continue
        for row in rows:
            try:
                single = {table_name: [row]}
                conn.execute("BEGIN")
                _execute_inserts(conn, single)
                conn.execute("COMMIT")
            except Exception as exc:
                conn.execute("ROLLBACK")
                if verbose:
                    print(
                        f"  WARN: skipped bad row in {table_name}: {exc}",
                        file=sys.stderr,
                    )


def _write_to_duckdb(  # pyright: ignore[reportUnusedFunction]  # used by tests via importlib
    output_path: Path,
    results: list[dict[str, Any]],
    *,
    template_family_map: dict[str, str] | None = None,
    verbose: bool = False,
) -> None:
    """Backward-compatible wrapper: write all results to DuckDB in one shot."""
    conn = _init_db(output_path)
    try:
        seen_doc_ids: set[str] = set()
        _write_batch(conn, results, seen_doc_ids, template_family_map, verbose)
        if verbose:
            count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            print(f"  Wrote {count} documents to {output_path}", file=sys.stderr)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Anomaly report from DuckDB (Step 3)
# ---------------------------------------------------------------------------


def _build_anomaly_rows_from_db(conn: Any) -> list[dict[str, Any]]:
    """Build anomaly report rows by querying the DuckDB documents table."""
    rows_raw = conn.execute("""
        SELECT doc_id, path, template_family, section_count, clause_count,
               definition_count, word_count, text_length, section_parser_mode,
               section_fallback_used
        FROM documents
        WHERE section_count = 0 OR clause_count = 0
        ORDER BY template_family, doc_id
    """).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows_raw:
        (doc_id, path, template_family, section_count, clause_count,
         definition_count, word_count, text_length, section_parser_mode,
         section_fallback_used) = row
        signatures = _derive_failure_signatures(
            section_count=int(section_count or 0),
            clause_count=int(clause_count or 0),
            word_count=int(word_count or 0),
            text_length=int(text_length or 0),
            section_fallback_used=bool(section_fallback_used),
        )
        result.append({
            "doc_id": doc_id,
            "path": path or "",
            "template_family": template_family or "unknown",
            "section_count": int(section_count or 0),
            "clause_count": int(clause_count or 0),
            "definition_count": int(definition_count or 0),
            "word_count": int(word_count or 0),
            "text_length": int(text_length or 0),
            "section_parser_mode": section_parser_mode or "",
            "section_fallback_used": bool(section_fallback_used),
            "failure_signatures": signatures,
        })
    return result


# ---------------------------------------------------------------------------
# Build manifest (Step 4 — incremental)
# ---------------------------------------------------------------------------


def _load_build_manifest(path: Path) -> dict[str, Any]:
    """Load build manifest from disk. Returns empty dict on failure."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _save_build_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Atomic write: write to temp file then os.replace()."""
    tmp = Path(f"{path}.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(str(tmp), str(path))


def _diff_corpus(
    discovered_files: list[Path],
    manifest_data: dict[str, Any],
    corpus_dir: Path,
) -> tuple[list[Path], list[Path], list[str]]:
    """Diff discovered files against build manifest.

    Returns (new_files, changed_files, deleted_doc_ids).
    """
    files_in_manifest = manifest_data.get("files", {})
    new_files: list[Path] = []
    changed_files: list[Path] = []

    discovered_rel_paths: set[str] = set()
    for f in discovered_files:
        try:
            rel = str(f.relative_to(corpus_dir))
        except ValueError:
            rel = str(f)
        discovered_rel_paths.add(rel)

        entry = files_in_manifest.get(rel)
        if entry is None:
            new_files.append(f)
        else:
            stat = f.stat()
            if (
                int(stat.st_mtime_ns) != entry.get("mtime_ns")
                or stat.st_size != entry.get("size_bytes")
            ):
                changed_files.append(f)

    deleted_doc_ids: list[str] = []
    for rel, entry in files_in_manifest.items():
        if rel not in discovered_rel_paths:
            doc_id = entry.get("doc_id", "")
            if doc_id:
                deleted_doc_ids.append(doc_id)

    return new_files, changed_files, deleted_doc_ids


def _delete_doc_ids(conn: Any, doc_ids: list[str]) -> None:
    """Delete rows for given doc_ids from all 7 data tables in a transaction."""
    if not doc_ids:
        return
    conn.execute("BEGIN")
    try:
        # Delete in reverse dependency order
        tables = [
            "clause_features", "section_features", "section_text",
            "clauses", "definitions", "sections", "documents",
        ]
        for table in tables:
            placeholders = ", ".join("?" for _ in doc_ids)
            conn.execute(
                f"DELETE FROM {table} WHERE doc_id IN ({placeholders})",
                doc_ids,
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Table-specific rebuild (Step 5)
# ---------------------------------------------------------------------------

_TABLE_DEPS: dict[str, set[str]] = {
    "sections": {"section_text", "section_features", "clauses", "clause_features"},
    "clauses": {"clause_features"},
    "definitions": set(),
    "section_text": set(),
    "section_features": set(),
    "clause_features": set(),
}

_ALL_DATA_TABLES = frozenset({
    "documents", "sections", "clauses", "definitions",
    "section_text", "section_features", "clause_features",
})


def _resolve_table_deps(requested: set[str]) -> set[str]:
    """Expand requested tables to include all dependents."""
    expanded = set(requested)
    changed = True
    while changed:
        changed = False
        for table in list(expanded):
            deps = _TABLE_DEPS.get(table, set())
            for dep in deps:
                if dep not in expanded:
                    expanded.add(dep)
                    changed = True
    return expanded


def _delete_table_rows_for_doc(conn: Any, doc_id: str, tables: set[str]) -> None:
    """Delete rows for a doc_id from the specified tables only."""
    # Delete in reverse dependency order
    ordered = [
        "clause_features", "section_features", "section_text",
        "clauses", "definitions", "sections",
    ]
    for table in ordered:
        if table in tables:
            conn.execute(f"DELETE FROM {table} WHERE doc_id = ?", [doc_id])


def _reprocess_tables_for_doc(
    args: tuple[str, str, Path, set[str]],
) -> dict[str, list[dict[str, Any]]] | None:
    """Re-read HTML and run only the needed parsers for a single document.

    Args is (doc_id, rel_path, corpus_dir, tables).
    """
    doc_id, rel_path, corpus_dir, tables = args
    file_path = corpus_dir / rel_path
    try:
        html = read_file(file_path)
        if not html:
            return None
        normalized_text, _ = normalize_html(html)
        if not normalized_text:
            return None

        result: dict[str, list[dict[str, Any]]] = {"doc_id_str": [{"doc_id": doc_id}]}

        need_sections = (
            "sections" in tables
            or "section_text" in tables
            or "section_features" in tables
        )
        need_clauses = "clauses" in tables or "clause_features" in tables

        all_sections_list: list[OutlineSection] = []
        if need_sections or need_clauses:
            outline = DocOutline.from_text(normalized_text, filename=file_path.name)
            all_sections_list = outline.sections
            if not all_sections_list:
                from agent.section_parser import find_sections
                all_sections_list = find_sections(normalized_text)  # type: ignore[assignment]

        if "sections" in tables:
            result["sections"] = [
                {
                    "doc_id": doc_id,
                    "section_number": s.number,
                    "heading": s.heading,
                    "char_start": s.char_start,
                    "char_end": s.char_end,
                    "article_num": s.article_num,
                    "word_count": s.word_count,
                }
                for s in all_sections_list
            ]

        if "section_text" in tables:
            result["section_texts"] = [
                {
                    "doc_id": doc_id,
                    "section_number": s.number,
                    "text": normalized_text[s.char_start:s.char_end],
                }
                for s in all_sections_list
            ]

        if "section_features" in tables:
            result["section_features"] = [
                build_section_feature(
                    doc_id=doc_id,
                    section_number=s.number,
                    heading=s.heading,
                    text=normalized_text[s.char_start:s.char_end],
                    char_start=s.char_start,
                    char_end=s.char_end,
                    article_num=s.article_num,
                    word_count=s.word_count,
                )
                for s in all_sections_list
            ]

        if need_clauses:
            all_clauses_list: list[tuple[str, ClauseNode]] = []
            for section in all_sections_list:
                slice_text = normalized_text[section.char_start:section.char_end]
                parsed = parse_clauses(slice_text, global_offset=section.char_start)
                for clause in parsed:
                    all_clauses_list.append((section.number, clause))

            if "clauses" in tables:
                clause_recs = []
                for sec_num, clause in all_clauses_list:
                    ct = ""
                    if 0 <= clause.span_start < clause.span_end <= len(normalized_text):
                        ct = normalized_text[clause.span_start:clause.span_end]
                    clause_recs.append({
                        "doc_id": doc_id,
                        "section_number": sec_num,
                        "clause_id": clause.id,
                        "label": clause.label,
                        "depth": clause.depth,
                        "level_type": clause.level_type,
                        "span_start": clause.span_start,
                        "span_end": clause.span_end,
                        "header_text": clause.header_text,
                        "clause_text": ct,
                        "parent_id": clause.parent_id,
                        "is_structural": clause.is_structural_candidate,
                        "parse_confidence": clause.parse_confidence,
                    })
                result["clauses"] = clause_recs

            if "clause_features" in tables:
                cf_recs = []
                for sec_num, clause in all_clauses_list:
                    ct = ""
                    if 0 <= clause.span_start < clause.span_end <= len(normalized_text):
                        ct = normalized_text[clause.span_start:clause.span_end]
                    cf_recs.append(
                        build_clause_feature(
                            doc_id=doc_id,
                            section_number=sec_num,
                            clause_id=clause.id,
                            depth=clause.depth,
                            level_type=clause.level_type,
                            clause_text=ct,
                            parse_confidence=clause.parse_confidence,
                            is_structural=clause.is_structural_candidate,
                        )
                    )
                result["clause_features"] = cf_recs

        if "definitions" in tables:
            definitions = extract_definitions(normalized_text)
            result["definitions"] = [
                {
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
                }
                for defn in definitions
            ]

        # Compute updated counts for documents table update
        count_updates: dict[str, int] = {}
        if "sections" in tables:
            count_updates["section_count"] = len(result.get("sections", []))
        if "clauses" in tables:
            count_updates["clause_count"] = len(result.get("clauses", []))
        if "definitions" in tables:
            count_updates["definition_count"] = len(result.get("definitions", []))
        result["_count_updates"] = [count_updates]  # type: ignore[assignment]

        return result

    except Exception as exc:
        print(f"  ERROR reprocessing {rel_path}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    run_id = generate_run_id("local_corpus_build")
    t0 = time.time()

    parser = argparse.ArgumentParser(
        description="Build a DuckDB corpus index from HTML credit agreement documents.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        required=True,
        help="Directory containing HTML files (*.htm, *.html)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to output DuckDB file",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N files (for testing)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file without confirmation",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print progress to stderr",
    )
    parser.add_argument(
        "--template-classifications",
        type=Path,
        default=None,
        help=(
            "Optional classifications JSON (doc_id -> template_family payload) "
            "to reapply template labels during build."
        ),
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
        "--batch-size",
        type=int,
        default=100,
        help="Number of documents per DuckDB write batch (default: 100)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Only process changed/new files using build manifest. "
            "Incompatible with --limit and --tables."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Custom build manifest path (default: {output}.build_manifest.json)",
    )
    parser.add_argument(
        "--tables",
        type=str,
        default=None,
        help=(
            "Comma-separated table names to rebuild (e.g. 'sections,clauses'). "
            "Dependents are auto-included. Requires --corpus-dir. "
            "Incompatible with --incremental."
        ),
    )
    parser.add_argument(
        "--one-per-cik",
        action="store_true",
        help=(
            "Keep only the most recent filing per CIK. "
            "Eliminates overweighting of borrowers with many filings."
        ),
    )
    args = parser.parse_args()

    corpus_dir: Path = args.corpus_dir.resolve()
    output_path: Path = args.output.resolve()
    workers: int = args.workers
    limit: int | None = args.limit
    force: bool = args.force
    verbose: bool = args.verbose
    template_classifications: Path | None = args.template_classifications
    anomaly_output: Path | None = args.anomaly_output
    batch_size: int = args.batch_size
    incremental: bool = args.incremental
    one_per_cik: bool = args.one_per_cik
    manifest_path: Path = (
        args.manifest.resolve()
        if args.manifest
        else Path(f"{output_path}.build_manifest.json")
    )
    tables_arg: str | None = args.tables

    # --- Flag compatibility checks ---
    if incremental and limit is not None:
        print(
            "ERROR: --incremental and --limit are incompatible.",
            file=sys.stderr,
        )
        sys.exit(1)
    if incremental and tables_arg is not None:
        print(
            "ERROR: --incremental and --tables are incompatible.",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Parse --tables ---
    rebuild_tables: set[str] | None = None
    if tables_arg is not None:
        raw_tables = {t.strip() for t in tables_arg.split(",") if t.strip()}
        invalid = raw_tables - _ALL_DATA_TABLES
        if invalid:
            print(
                f"ERROR: unknown table names: {', '.join(sorted(invalid))}. "
                f"Valid: {', '.join(sorted(_ALL_DATA_TABLES))}",
                file=sys.stderr,
            )
            sys.exit(1)
        rebuild_tables = _resolve_table_deps(raw_tables)
        if verbose:
            print(
                f"Table-specific rebuild: {', '.join(sorted(rebuild_tables))}",
                file=sys.stderr,
            )

    # Validate corpus directory
    if not corpus_dir.is_dir():
        print(f"ERROR: corpus directory not found: {corpus_dir}", file=sys.stderr)
        sys.exit(1)

    # Load template family map early (used by both full and incremental)
    template_family_map: dict[str, str] | None = None
    if template_classifications is not None:
        tpath = template_classifications.resolve()
        if not tpath.exists():
            print(
                f"ERROR: template classifications file not found: {tpath}",
                file=sys.stderr,
            )
            sys.exit(1)
        template_family_map = _load_template_family_map(tpath)
        if verbose:
            print(
                f"Loaded {len(template_family_map)} template-family mappings "
                f"from {tpath}",
                file=sys.stderr,
            )

    # ==================================================================
    # TABLE-SPECIFIC REBUILD PATH (--tables)
    # ==================================================================
    if rebuild_tables is not None:
        if not output_path.exists():
            print(
                f"ERROR: --tables requires an existing DuckDB file: {output_path}",
                file=sys.stderr,
            )
            sys.exit(1)

        conn: Any = _duckdb.connect(str(output_path))
        try:
            # Get all documents
            doc_rows = conn.execute(
                "SELECT doc_id, path FROM documents",
            ).fetchall()
            total_docs = len(doc_rows)
            if verbose:
                print(
                    f"Table-specific rebuild for {total_docs} documents...",
                    file=sys.stderr,
                )

            progress = _ProgressReporter(total_docs)
            errors = 0

            # Process in batches
            work_items_tables = [
                (row[0], row[1], corpus_dir, rebuild_tables)
                for row in doc_rows
            ]

            batch_results: list[dict[str, list[dict[str, Any]]]] = []
            batch_doc_ids: list[str] = []

            def _flush_table_batch() -> None:
                nonlocal batch_results, batch_doc_ids
                if not batch_results:
                    return
                conn.execute("BEGIN")
                try:
                    # Delete old rows for affected tables
                    for did in batch_doc_ids:
                        _delete_table_rows_for_doc(conn, did, rebuild_tables)  # type: ignore[arg-type]
                    # Insert new rows
                    for res in batch_results:
                        did = res["doc_id_str"][0]["doc_id"]  # type: ignore[index]
                        for table in sorted(rebuild_tables):  # type: ignore[arg-type]
                            key_map = {
                                "sections": "sections",
                                "section_text": "section_texts",
                                "section_features": "section_features",
                                "clauses": "clauses",
                                "clause_features": "clause_features",
                                "definitions": "definitions",
                            }
                            recs = res.get(key_map.get(table, table), [])
                            if not recs:
                                continue
                            _DOC_STUB_KEYS = (
                                "cik", "accession", "path",
                                "borrower", "admin_agent",
                                "facility_size_mm",
                                "facility_confidence",
                                "closing_ebitda_mm",
                                "ebitda_confidence",
                                "closing_date", "filing_date",
                                "form_type", "template_family",
                                "doc_type", "doc_type_confidence",
                                "market_segment",
                                "segment_confidence",
                                "cohort_included", "word_count",
                                "section_count", "clause_count",
                                "definition_count", "text_length",
                            )
                            stub = {
                                "doc_id": did,
                                **{k: None for k in _DOC_STUB_KEYS},
                            }
                            tuples_data = _prepare_batch_tuples(
                                [{"doc": stub, table: recs}],
                                set(),
                                None,
                                False,
                            )
                            for tbl, tpls in tuples_data.items():
                                if tbl == table and tpls:
                                    single_table = {tbl: tpls}
                                    _execute_inserts(conn, single_table)

                        # Update document counts if applicable
                        count_updates = res.get("_count_updates", [{}])[0]
                        if count_updates:
                            set_clauses = []
                            params: list[Any] = []
                            for col, val in count_updates.items():
                                set_clauses.append(f"{col} = ?")
                                params.append(val)
                            params.append(did)
                            conn.execute(
                                f"UPDATE documents SET {', '.join(set_clauses)} WHERE doc_id = ?",
                                params,
                            )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                batch_results.clear()
                batch_doc_ids.clear()

            if workers <= 1:
                for item in work_items_tables:
                    res = _reprocess_tables_for_doc(item)
                    if res is not None:
                        batch_results.append(res)
                        batch_doc_ids.append(item[0])
                    else:
                        errors += 1
                    progress.tick(error=res is None)
                    if len(batch_results) >= batch_size:
                        _flush_table_batch()
            else:
                with Pool(processes=workers) as pool:
                    for res in pool.imap_unordered(
                        _reprocess_tables_for_doc, work_items_tables,
                    ):
                        if res is not None:
                            did = res["doc_id_str"][0]["doc_id"]  # type: ignore[index]
                            batch_results.append(res)
                            batch_doc_ids.append(did)
                        else:
                            errors += 1
                        progress.tick(error=res is None)
                        if len(batch_results) >= batch_size:
                            _flush_table_batch()

            _flush_table_batch()
            progress.finish()

            print(
                f"Table-specific rebuild complete: "
                f"{total_docs - errors} docs updated, {errors} errors",
                file=sys.stderr,
            )
        finally:
            conn.close()
        return

    # ==================================================================
    # INCREMENTAL REBUILD PATH (--incremental)
    # ==================================================================
    manifest_data: dict[str, Any] = {}
    if incremental:
        if verbose:
            print("Incremental mode: checking build manifest...", file=sys.stderr)

        manifest_data = _load_build_manifest(manifest_path)
        if not manifest_data:
            print(
                "WARN: No valid build manifest found — falling back to full rebuild.",
                file=sys.stderr,
            )
            incremental = False
        elif not output_path.exists():
            print(
                "WARN: DuckDB file not found — falling back to full rebuild.",
                file=sys.stderr,
            )
            incremental = False

    if incremental:
        # Discover all files (no limit in incremental mode)
        html_files = _discover_html_files(corpus_dir)
        new_files, changed_files, deleted_doc_ids = _diff_corpus(
            html_files, manifest_data, corpus_dir,
        )

        if not new_files and not changed_files and not deleted_doc_ids:
            print("Nothing to do: all files are up-to-date.", file=sys.stderr)
            return

        if verbose:
            print(
                f"Incremental: {len(new_files)} new, {len(changed_files)} changed, "
                f"{len(deleted_doc_ids)} deleted",
                file=sys.stderr,
            )

        # Get old doc_ids for changed files from manifest
        changed_old_doc_ids: list[str] = []
        for f in changed_files:
            try:
                rel = str(f.relative_to(corpus_dir))
            except ValueError:
                rel = str(f)
            entry = manifest_data.get("files", {}).get(rel)
            if entry and entry.get("doc_id"):
                changed_old_doc_ids.append(entry["doc_id"])

        # Open existing DB and delete changed+deleted doc_ids
        conn = _duckdb.connect(str(output_path))
        try:
            all_delete_ids = deleted_doc_ids + changed_old_doc_ids
            if all_delete_ids:
                _delete_doc_ids(conn, all_delete_ids)
                if verbose:
                    print(
                        f"Deleted {len(all_delete_ids)} doc_ids from DB",
                        file=sys.stderr,
                    )

            # Process new + changed files
            to_process = new_files + changed_files
            total = len(to_process)
            work_items_inc: list[tuple[Path, Path, int, int]] = [
                (f, corpus_dir, i, total)
                for i, f in enumerate(to_process)
            ]

            progress = _ProgressReporter(total)
            seen_doc_ids: set[str] = set()
            stats = _RunStats()
            errors = 0
            batch: list[dict[str, Any]] = []

            def _flush_incremental_batch() -> None:
                nonlocal batch
                if not batch:
                    return
                _write_batch(conn, batch, seen_doc_ids, template_family_map, verbose)
                # Update manifest incrementally
                files_map = manifest_data.setdefault("files", {})
                for res in batch:
                    doc = res["doc"]
                    path_str = doc["path"]
                    full_path = corpus_dir / path_str
                    try:
                        stat = full_path.stat()
                        files_map[path_str] = {
                            "mtime_ns": int(stat.st_mtime_ns),
                            "size_bytes": stat.st_size,
                            "doc_id": doc["doc_id"],
                        }
                    except OSError:
                        pass
                _save_build_manifest(manifest_path, manifest_data)
                batch.clear()

            if workers <= 1:
                for item in work_items_inc:
                    result = _process_one_doc(item)
                    if result is not None:
                        batch.append(result)
                        stats.accumulate(result)
                    else:
                        errors += 1
                    progress.tick(error=result is None)
                    if len(batch) >= batch_size:
                        _flush_incremental_batch()
            else:
                with Pool(processes=workers) as pool:
                    for result in pool.imap_unordered(
                        _process_one_doc, work_items_inc,
                    ):
                        if result is not None:
                            batch.append(result)
                            stats.accumulate(result)
                        else:
                            errors += 1
                        progress.tick(error=result is None)
                        if len(batch) >= batch_size:
                            _flush_incremental_batch()

            _flush_incremental_batch()
            progress.finish()

            # Remove deleted files from manifest
            files_map = manifest_data.get("files", {})
            for rel in list(files_map.keys()):
                full_path = corpus_dir / rel
                if not full_path.exists():
                    del files_map[rel]
            manifest_data["built_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
            )
            _save_build_manifest(manifest_path, manifest_data)

            # Warn about doc_id changes
            for f in changed_files:
                try:
                    rel = str(f.relative_to(corpus_dir))
                except ValueError:
                    rel = str(f)
                # Manifest already updated per-batch above

            print(
                f"Incremental rebuild complete: "
                f"{stats.processed_docs} docs processed, "
                f"{len(deleted_doc_ids)} deleted, {errors} errors",
                file=sys.stderr,
            )

        finally:
            conn.close()
        return

    # ==================================================================
    # FULL REBUILD PATH (default)
    # ==================================================================

    # Check output file
    if output_path.exists() and not force:
        response = input(
            f"Output file already exists: {output_path}\n"
            f"Overwrite? [y/N] "
        )
        if response.strip().lower() not in ("y", "yes"):
            print("Aborted.", file=sys.stderr)
            sys.exit(0)
        output_path.unlink()
    elif output_path.exists() and force:
        output_path.unlink()

    # Step 1: Discover HTML files
    if verbose:
        print(f"Discovering HTML files in {corpus_dir}...", file=sys.stderr)

    html_files = _discover_html_files(corpus_dir, limit=limit)

    if one_per_cik:
        html_files = _dedup_by_cik_paths(html_files, verbose=verbose)

    t_discover_done = time.time()
    total = len(html_files)

    if total == 0:
        print(f"ERROR: No HTML files found in {corpus_dir}", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f"Found {total} HTML files", file=sys.stderr)

    # Step 2: Process all files with batched writes
    work_items: list[tuple[Path, Path, int, int]] = [
        (f, corpus_dir, i, total)
        for i, f in enumerate(html_files)
    ]

    conn = _init_db(output_path)
    batch: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()
    progress = _ProgressReporter(total)
    stats = _RunStats()
    errors = 0

    # Build manifest data structure (saved at end for full rebuild)
    build_manifest_data: dict[str, Any] = {
        "schema_version": "build_manifest_v1",
        "built_at": "",
        "files": {},
    }

    try:
        if workers <= 1:
            for item in work_items:
                result = _process_one_doc(item)
                if result is not None:
                    batch.append(result)
                    stats.accumulate(result)
                else:
                    errors += 1
                progress.tick(error=result is None)
                if len(batch) >= batch_size:
                    _write_batch(conn, batch, seen_doc_ids, template_family_map, verbose)
                    batch.clear()
        else:
            if verbose:
                print(f"Processing with {workers} workers...", file=sys.stderr)
            with Pool(processes=workers) as pool:
                for result in pool.imap_unordered(
                    _process_one_doc, work_items,
                ):
                    if result is not None:
                        batch.append(result)
                        stats.accumulate(result)
                    else:
                        errors += 1
                    progress.tick(error=result is None)
                    if len(batch) >= batch_size:
                        _write_batch(
                            conn, batch, seen_doc_ids, template_family_map, verbose,
                        )
                        batch.clear()

        # Final partial batch
        if batch:
            _write_batch(conn, batch, seen_doc_ids, template_family_map, verbose)
            batch.clear()

        progress.finish()

        if stats.processed_docs == 0:
            print(
                "ERROR: No documents were successfully processed.",
                file=sys.stderr,
            )
            conn.close()
            sys.exit(1)

        t_process_done = time.time()

        # Anomaly report from DB
        anomaly_rows = _build_anomaly_rows_from_db(conn)

    finally:
        conn.close()

    t_write_done = time.time()

    # Save build manifest for future --incremental runs
    files_map: dict[str, Any] = {}
    for f in html_files:
        try:
            rel = str(f.relative_to(corpus_dir))
            stat = f.stat()
            # We need the doc_id — but after batched writes we don't have
            # results in memory. Query the DB for it.
        except (ValueError, OSError):
            pass
    # Re-open DB read-only to get doc_id mapping by path
    conn_ro: Any = _duckdb.connect(str(output_path), read_only=True)
    try:
        path_to_doc_id: dict[str, str] = {}
        rows_all = conn_ro.execute("SELECT doc_id, path FROM documents").fetchall()
        for row in rows_all:
            path_to_doc_id[row[1]] = row[0]
    finally:
        conn_ro.close()

    for f in html_files:
        try:
            rel = str(f.relative_to(corpus_dir))
            stat = f.stat()
            files_map[rel] = {
                "mtime_ns": int(stat.st_mtime_ns),
                "size_bytes": stat.st_size,
                "doc_id": path_to_doc_id.get(rel, ""),
            }
        except (ValueError, OSError):
            pass

    build_manifest_data["built_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
    )
    build_manifest_data["files"] = files_map
    _save_build_manifest(manifest_path, build_manifest_data)

    # Anomaly report
    anomaly_report_path = (
        anomaly_output.resolve()
        if anomaly_output is not None
        else output_path.with_suffix(".anomalies.json")
    )
    anomaly_report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_anomaly_report(
        anomaly_report_path,
        anomaly_rows,
        requested_docs=total,
        processed_docs=stats.processed_docs,
        errors=errors,
    )

    # Summary (from _RunStats, not from iterating results)
    excluded_count = stats.processed_docs - stats.cohort_count

    print(
        f"Built corpus index: {stats.processed_docs} docs, "
        f"{stats.total_sections} sections, "
        f"{stats.total_clauses} clauses, {stats.total_definitions} definitions, "
        f"{stats.total_section_features} section_features, "
        f"{stats.total_clause_features} clause_features",
        file=sys.stderr,
    )
    print(f"Output: {output_path}", file=sys.stderr)
    print(
        f"Parse anomalies: {len(anomaly_rows)} (report: {anomaly_report_path})",
        file=sys.stderr,
    )

    print("\n--- Cohort Summary ---", file=sys.stderr)
    print(f"  Cohort (leveraged CAs): {stats.cohort_count}", file=sys.stderr)
    print(f"  Excluded: {excluded_count}", file=sys.stderr)
    print("  Doc type breakdown:", file=sys.stderr)
    for dt, count in sorted(stats.doc_type_counts.items()):
        print(f"    {dt}: {count}", file=sys.stderr)
    if stats.segment_counts:
        print("  Market segment (CAs only):", file=sys.stderr)
        for seg, count in sorted(stats.segment_counts.items()):
            print(f"    {seg}: {count}", file=sys.stderr)

    timings = {
        "discover": round(t_discover_done - t0, 3),
        "process": round(t_process_done - t_discover_done, 3),
        "write": round(t_write_done - t_process_done, 3),
        "total": round(t_write_done - t0, 3),
    }
    run_manifest = build_manifest(
        run_id=run_id,
        db_path=output_path,
        input_source={
            "mode": "local_filesystem",
            "corpus_dir": str(corpus_dir),
            "limit": limit,
            "workers": workers,
            "batch_size": batch_size,
            "template_classifications": (
                str(template_classifications.resolve())
                if template_classifications is not None
                else None
            ),
        },
        timings_sec=timings,
        errors_count=errors,
        stats={
            "processed_docs": stats.processed_docs,
            "requested_docs": total,
            "cohort_docs": stats.cohort_count,
            "excluded_docs": excluded_count,
            "section_features": stats.total_section_features,
            "clause_features": stats.total_clause_features,
            "parse_anomaly_count": len(anomaly_rows),
            "parse_anomaly_report": str(anomaly_report_path),
        },
        git_commit=git_commit_hash(search_from=Path(__file__).resolve().parents[1]),
    )
    manifest_out_path, versioned_manifest_path = write_manifest(
        output_path, run_manifest,
    )
    print(f"Run manifest: {manifest_out_path}", file=sys.stderr)
    print(f"Versioned manifest: {versioned_manifest_path}", file=sys.stderr)
    print(f"Build manifest: {manifest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
