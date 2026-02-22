#!/usr/bin/env python3
"""Build a DuckDB corpus index from HTML credit agreement documents.

Reads HTML credit agreement files from a corpus directory, processes each
one through the agent library (HTML normalization, section parsing, clause
parsing, definition extraction), and writes the results to a DuckDB
database file.

Usage:
    python3 scripts/build_corpus_index.py \
        --corpus-dir corpus/ \
        --output corpus_index/corpus.duckdb \
        --workers 4
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import re
import sys
import traceback
from multiprocessing import Pool
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Agent library imports
# ---------------------------------------------------------------------------

from agent.html_utils import normalize_html, read_file, strip_html
from agent.section_parser import OutlineArticle, OutlineSection, parse_outline
from agent.clause_parser import ClauseNode, parse_clauses
from agent.definitions import DefinedTerm, extract_definitions
from agent.io_utils import load_json

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

INSERT INTO _schema_version VALUES ('corpus', '0.1.0', current_timestamp);

CREATE TABLE documents (
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
    section_count INTEGER DEFAULT 0,
    clause_count INTEGER DEFAULT 0,
    definition_count INTEGER DEFAULT 0,
    text_length INTEGER DEFAULT 0
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
    parent_id VARCHAR DEFAULT '',
    is_structural BOOLEAN DEFAULT true,
    parse_confidence DOUBLE DEFAULT 0.0,
    PRIMARY KEY (doc_id, clause_id)
);

CREATE TABLE definitions (
    doc_id VARCHAR NOT NULL,
    term VARCHAR NOT NULL,
    definition_text VARCHAR,
    char_start INTEGER,
    char_end INTEGER,
    pattern_engine VARCHAR,
    confidence DOUBLE DEFAULT 0.0
);

CREATE TABLE section_text (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    text VARCHAR,
    PRIMARY KEY (doc_id, section_number)
);
"""

# ---------------------------------------------------------------------------
# CIK extraction from path
# ---------------------------------------------------------------------------

_CIK_DIR_RE = re.compile(r"cik=(\d{10})")
_ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")


def _extract_cik(path: Path) -> str:
    """Extract CIK from a path containing cik=XXXXXXXXXX directory."""
    for part in path.parts:
        m = _CIK_DIR_RE.search(part)
        if m:
            return m.group(1)
    return ""


def _extract_accession(path: Path) -> str:
    """Extract accession number from filename or path."""
    # Try the filename first (most common)
    m = _ACCESSION_RE.search(path.stem)
    if m:
        return m.group(1)
    # Try full path
    for part in path.parts:
        m = _ACCESSION_RE.search(part)
        if m:
            return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# doc_id computation
# ---------------------------------------------------------------------------


def _compute_doc_id(path: Path) -> str:
    """Compute a deterministic doc_id: SHA-256 of (filename + file_size), truncated to 16 hex chars."""
    file_size = path.stat().st_size
    key = f"{path.name}{file_size}"
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return h[:16]


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
    accession = _extract_accession(file_path)
    if accession:
        parts[-1] = f"{accession}.meta.json"
    else:
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


# ---------------------------------------------------------------------------
# Section assignment helper
# ---------------------------------------------------------------------------


def _assign_section_number(
    section: OutlineSection,
    clause: ClauseNode,
) -> bool:
    """Return True if the clause falls within this section's char range."""
    return section.char_start <= clause.span_start < section.char_end


# ---------------------------------------------------------------------------
# Single-document processing
# ---------------------------------------------------------------------------


def _process_one_doc(
    args: tuple[Path, Path, int, int],
) -> dict[str, Any] | None:
    """Process a single HTML document and return extracted data.

    Args is a tuple of (file_path, corpus_dir, file_index, total_files).
    Returns a dict with keys: doc, sections, clauses, definitions, section_texts.
    Returns None on failure.
    """
    file_path, corpus_dir, file_index, total_files = args

    try:
        # Step a: Read file (encoding-safe)
        html = read_file(file_path)
        if not html:
            print(
                f"  SKIP {file_path.name}: empty or unreadable",
                file=sys.stderr,
            )
            return None

        # Step b: Strip HTML for simple text
        text = strip_html(html)
        if not text or len(text) < 100:
            print(
                f"  SKIP {file_path.name}: text too short ({len(text)} chars)",
                file=sys.stderr,
            )
            return None

        # Step c: Normalize HTML (text + inverse map)
        normalized_text, _inverse_map = normalize_html(html)

        # Step d: Compute doc_id
        doc_id = _compute_doc_id(file_path)

        # Step e: Parse outline (articles and sections)
        articles: list[OutlineArticle] = parse_outline(normalized_text)

        # Flatten sections from all articles
        all_sections: list[OutlineSection] = []
        for article in articles:
            all_sections.extend(article.sections)

        # If no articles found, try direct section finding
        if not all_sections:
            from agent.section_parser import find_sections
            all_sections = find_sections(normalized_text)

        # Step f: Parse clauses for each section
        all_clauses: list[tuple[str, ClauseNode]] = []  # (section_number, clause)
        for section in all_sections:
            section_text_slice = normalized_text[section.char_start:section.char_end]
            clauses = parse_clauses(
                section_text_slice,
                global_offset=section.char_start,
            )
            for clause in clauses:
                all_clauses.append((section.number, clause))

        # Step g: Extract definitions from full text
        definitions: list[DefinedTerm] = extract_definitions(normalized_text)

        # Step h: Extract metadata from path
        cik = _extract_cik(file_path)
        accession = _extract_accession(file_path)

        # Step i: Merge sidecar metadata if present
        meta_sidecar = _find_meta_sidecar(file_path, corpus_dir)
        sidecar_data: dict[str, Any] = {}
        if meta_sidecar is not None:
            sidecar_data = _load_sidecar_metadata(meta_sidecar)
            # Override with sidecar values if available
            if sidecar_data.get("cik"):
                cik = str(sidecar_data["cik"])
            if sidecar_data.get("accession"):
                accession = str(sidecar_data["accession"])

        # Build the relative path for storage
        try:
            rel_path = str(file_path.relative_to(corpus_dir))
        except ValueError:
            rel_path = str(file_path)

        # Build document record
        doc_record = {
            "doc_id": doc_id,
            "cik": cik,
            "accession": accession,
            "path": rel_path,
            "borrower": str(sidecar_data.get("company_name", "")),
            "admin_agent": "",
            "facility_size_mm": None,
            "closing_date": None,
            "filing_date": None,
            "form_type": "",
            "template_family": "",
            "section_count": len(all_sections),
            "clause_count": len(all_clauses),
            "definition_count": len(definitions),
            "text_length": len(normalized_text),
        }

        # Build section records
        section_records = []
        section_text_records = []
        for section in all_sections:
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
                "text": normalized_text[section.char_start:section.char_end],
            })

        # Build clause records
        clause_records = []
        for section_number, clause in all_clauses:
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
                "parent_id": clause.parent_id,
                "is_structural": clause.is_structural_candidate,
                "parse_confidence": clause.parse_confidence,
            })

        # Build definition records
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
            })

        return {
            "doc": doc_record,
            "sections": section_records,
            "clauses": clause_records,
            "definitions": def_records,
            "section_texts": section_text_records,
        }

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


# ---------------------------------------------------------------------------
# DuckDB writer
# ---------------------------------------------------------------------------


def _write_to_duckdb(
    output_path: Path,
    results: list[dict[str, Any]],
    verbose: bool = False,
) -> None:
    """Write all results to DuckDB in a single batch."""
    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn: Any = _duckdb.connect(str(output_path))
    try:
        # Create schema
        for stmt in _SCHEMA_DDL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)

        # Aggregate all records
        all_docs: list[dict[str, Any]] = []
        all_sections: list[dict[str, Any]] = []
        all_clauses: list[dict[str, Any]] = []
        all_definitions: list[dict[str, Any]] = []
        all_section_texts: list[dict[str, Any]] = []

        # Track doc_ids to avoid duplicates
        seen_doc_ids: set[str] = set()

        for result in results:
            doc = result["doc"]
            doc_id = doc["doc_id"]

            # Handle doc_id collisions (different files with same hash)
            if doc_id in seen_doc_ids:
                # Append a suffix to make it unique
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
                # Update all child records
                for rec in result["sections"]:
                    rec["doc_id"] = doc_id
                for rec in result["clauses"]:
                    rec["doc_id"] = doc_id
                for rec in result["definitions"]:
                    rec["doc_id"] = doc_id
                for rec in result["section_texts"]:
                    rec["doc_id"] = doc_id

            seen_doc_ids.add(doc_id)

            all_docs.append(doc)
            all_sections.extend(result["sections"])
            all_clauses.extend(result["clauses"])
            all_definitions.extend(result["definitions"])
            all_section_texts.extend(result["section_texts"])

        # Deduplicate clauses by (doc_id, clause_id) — keep first occurrence
        seen_clause_keys: set[tuple[str, str]] = set()
        deduped_clauses: list[dict[str, Any]] = []
        for clause in all_clauses:
            key = (clause["doc_id"], clause["clause_id"])
            if key not in seen_clause_keys:
                seen_clause_keys.add(key)
                deduped_clauses.append(clause)
        all_clauses = deduped_clauses

        # Batch insert: documents
        if all_docs:
            conn.executemany(
                """INSERT INTO documents
                   (doc_id, cik, accession, path, borrower, admin_agent,
                    facility_size_mm, closing_date, filing_date, form_type,
                    template_family, section_count, clause_count,
                    definition_count, text_length)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        d["doc_id"], d["cik"], d["accession"], d["path"],
                        d["borrower"], d["admin_agent"], d["facility_size_mm"],
                        d["closing_date"], d["filing_date"], d["form_type"],
                        d["template_family"], d["section_count"],
                        d["clause_count"], d["definition_count"],
                        d["text_length"],
                    )
                    for d in all_docs
                ],
            )

        # Batch insert: sections
        if all_sections:
            conn.executemany(
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

        # Batch insert: clauses
        if all_clauses:
            conn.executemany(
                """INSERT INTO clauses
                   (doc_id, section_number, clause_id, label, depth,
                    level_type, span_start, span_end, header_text,
                    parent_id, is_structural, parse_confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        c["doc_id"], c["section_number"], c["clause_id"],
                        c["label"], c["depth"], c["level_type"],
                        c["span_start"], c["span_end"], c["header_text"],
                        c["parent_id"], c["is_structural"],
                        c["parse_confidence"],
                    )
                    for c in all_clauses
                ],
            )

        # Batch insert: definitions
        if all_definitions:
            conn.executemany(
                """INSERT INTO definitions
                   (doc_id, term, definition_text, char_start, char_end,
                    pattern_engine, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        d["doc_id"], d["term"], d["definition_text"],
                        d["char_start"], d["char_end"], d["pattern_engine"],
                        d["confidence"],
                    )
                    for d in all_definitions
                ],
            )

        # Batch insert: section_text
        if all_section_texts:
            conn.executemany(
                """INSERT INTO section_text
                   (doc_id, section_number, text)
                   VALUES (?, ?, ?)""",
                [
                    (st["doc_id"], st["section_number"], st["text"])
                    for st in all_section_texts
                ],
            )

        if verbose:
            print(
                f"  Wrote {len(all_docs)} docs, {len(all_sections)} sections, "
                f"{len(all_clauses)} clauses, {len(all_definitions)} definitions",
                file=sys.stderr,
            )

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
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
    args = parser.parse_args()

    corpus_dir: Path = args.corpus_dir.resolve()
    output_path: Path = args.output.resolve()
    workers: int = args.workers
    limit: int | None = args.limit
    force: bool = args.force
    verbose: bool = args.verbose

    # Validate corpus directory
    if not corpus_dir.is_dir():
        print(f"ERROR: corpus directory not found: {corpus_dir}", file=sys.stderr)
        sys.exit(1)

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
    total = len(html_files)

    if total == 0:
        print(f"ERROR: No HTML files found in {corpus_dir}", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f"Found {total} HTML files", file=sys.stderr)

    # Step 2: Process all files in parallel
    work_items = [
        (f, corpus_dir, i, total)
        for i, f in enumerate(html_files)
    ]

    results: list[dict[str, Any]] = []
    errors = 0

    if workers <= 1:
        # Single-process mode (easier to debug)
        for i, item in enumerate(work_items):
            if verbose:
                print(
                    f"Processing {i + 1}/{total} files: {item[0].name}...",
                    file=sys.stderr,
                )
            result = _process_one_doc(item)
            if result is not None:
                results.append(result)
            else:
                errors += 1
    else:
        # Multiprocessing mode
        if verbose:
            print(f"Processing with {workers} workers...", file=sys.stderr)

        with Pool(processes=workers) as pool:
            for i, result in enumerate(
                pool.imap_unordered(_process_one_doc, work_items)
            ):
                if verbose and (i + 1) % 10 == 0:
                    print(
                        f"Processing {i + 1}/{total} files...",
                        file=sys.stderr,
                    )
                if result is not None:
                    results.append(result)
                else:
                    errors += 1

    if not results:
        print("ERROR: No documents were successfully processed.", file=sys.stderr)
        sys.exit(1)

    # Sort results by doc path for deterministic output
    results.sort(key=lambda r: r["doc"]["path"])

    if verbose:
        print(
            f"Successfully processed {len(results)}/{total} files "
            f"({errors} errors)",
            file=sys.stderr,
        )

    # Step 3: Write all results to DuckDB
    if verbose:
        print(f"Writing to {output_path}...", file=sys.stderr)

    _write_to_duckdb(output_path, results, verbose=verbose)

    # Summary
    total_sections = sum(len(r["sections"]) for r in results)
    total_clauses = sum(len(r["clauses"]) for r in results)
    total_definitions = sum(len(r["definitions"]) for r in results)

    print(
        f"Built corpus index: {len(results)} docs, {total_sections} sections, "
        f"{total_clauses} clauses, {total_definitions} definitions",
        file=sys.stderr,
    )
    print(f"Output: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
