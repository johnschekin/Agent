#!/usr/bin/env python3
"""Correctness gate for DuckDB outputs from build_corpus_ray_v2.py."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import duckdb

try:
    import orjson

    def _dump_json(obj: object) -> bytes:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2)

    def _load_json(data: bytes) -> Any:
        return orjson.loads(data)
except ImportError:

    def _dump_json(obj: object) -> bytes:
        return json.dumps(obj, indent=2, default=str).encode("utf-8")

    def _load_json(data: bytes) -> Any:
        return json.loads(data)


EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "documents": (
        "doc_id",
        "cik",
        "accession",
        "path",
        "borrower",
        "admin_agent",
        "facility_size_mm",
        "facility_confidence",
        "closing_ebitda_mm",
        "ebitda_confidence",
        "closing_date",
        "filing_date",
        "form_type",
        "template_family",
        "doc_type",
        "doc_type_confidence",
        "market_segment",
        "segment_confidence",
        "cohort_included",
        "word_count",
        "section_count",
        "clause_count",
        "definition_count",
        "text_length",
        "section_parser_mode",
        "section_fallback_used",
        "section_parser_trace",
    ),
    "articles": (
        "doc_id",
        "article_num",
        "label",
        "title",
        "concept",
        "char_start",
        "char_end",
        "is_synthetic",
    ),
    "sections": (
        "doc_id",
        "section_number",
        "heading",
        "char_start",
        "char_end",
        "article_num",
        "word_count",
    ),
    "clauses": (
        "doc_id",
        "section_number",
        "clause_id",
        "label",
        "depth",
        "level_type",
        "span_start",
        "span_end",
        "header_text",
        "clause_text",
        "parent_id",
        "is_structural",
        "parse_confidence",
    ),
    "definitions": (
        "doc_id",
        "term",
        "definition_text",
        "char_start",
        "char_end",
        "pattern_engine",
        "confidence",
        "definition_type",
        "definition_types",
        "type_confidence",
        "type_signals",
        "dependency_terms",
    ),
    "section_text": (
        "doc_id",
        "section_number",
        "text",
    ),
    "section_features": (
        "doc_id",
        "section_number",
        "article_num",
        "char_start",
        "char_end",
        "word_count",
        "char_count",
        "heading_lower",
        "scope_label",
        "scope_operator_count",
        "scope_permit_count",
        "scope_restrict_count",
        "scope_estimated_depth",
        "preemption_override_count",
        "preemption_yield_count",
        "preemption_estimated_depth",
        "preemption_has",
        "preemption_edge_count",
        "definition_types",
        "definition_type_primary",
        "definition_type_confidence",
    ),
    "clause_features": (
        "doc_id",
        "section_number",
        "clause_id",
        "depth",
        "level_type",
        "token_count",
        "char_count",
        "has_digits",
        "parse_confidence",
        "is_structural",
    ),
    "_schema_version": (
        "table_name",
        "version",
        "created_at",
    ),
}


def _count(conn: duckdb.DuckDBPyConnection, query: str) -> int:
    return int(conn.execute(query).fetchone()[0])


def _table_exists(conn: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    rows = conn.execute("SHOW TABLES").fetchall()
    return table_name in {r[0] for r in rows}


def _validate(db_path: Path, checkpoint_path: Path | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "database": str(db_path),
        "status": "pass",
        "tables": {},
        "checks": {},
        "warnings": [],
        "errors": [],
    }

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        for table_name, expected_cols in EXPECTED_COLUMNS.items():
            if not _table_exists(conn, table_name):
                report["errors"].append(f"Missing table: {table_name}")
                continue

            row_count = _count(conn, f"SELECT COUNT(*) FROM {table_name}")
            table_info = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            actual_cols = [row[1] for row in table_info]
            missing = [c for c in expected_cols if c not in actual_cols]
            extras = [c for c in actual_cols if c not in expected_cols]

            report["tables"][table_name] = {
                "rows": row_count,
                "missing_columns": missing,
                "extra_columns": extras,
            }
            if missing:
                report["errors"].append(
                    f"Table {table_name} missing columns: {', '.join(missing)}"
                )

        duplicate_checks = {
            "documents_pk_dupes": """
                SELECT COUNT(*) FROM (
                    SELECT doc_id, COUNT(*) AS n
                    FROM documents
                    GROUP BY doc_id
                    HAVING n > 1
                )
            """,
            "sections_pk_dupes": """
                SELECT COUNT(*) FROM (
                    SELECT doc_id, section_number, COUNT(*) AS n
                    FROM sections
                    GROUP BY doc_id, section_number
                    HAVING n > 1
                )
            """,
            "clauses_pk_dupes": """
                SELECT COUNT(*) FROM (
                    SELECT doc_id, section_number, clause_id, COUNT(*) AS n
                    FROM clauses
                    GROUP BY doc_id, section_number, clause_id
                    HAVING n > 1
                )
            """,
            "section_text_pk_dupes": """
                SELECT COUNT(*) FROM (
                    SELECT doc_id, section_number, COUNT(*) AS n
                    FROM section_text
                    GROUP BY doc_id, section_number
                    HAVING n > 1
                )
            """,
            "definitions_key_dupes": """
                SELECT COUNT(*) FROM (
                    SELECT
                        doc_id,
                        term,
                        COALESCE(char_start, -1) AS char_start_key,
                        COALESCE(char_end, -1) AS char_end_key,
                        COUNT(*) AS n
                    FROM definitions
                    GROUP BY doc_id, term, char_start_key, char_end_key
                    HAVING n > 1
                )
            """,
        }
        for check_name, query in duplicate_checks.items():
            dup_groups = _count(conn, query)
            report["checks"][check_name] = dup_groups
            if dup_groups > 0:
                report["errors"].append(f"{check_name}: {dup_groups} duplicate groups")

        orphan_checks: dict[str, str] = {
            "sections_orphans": """
                SELECT COUNT(*) FROM sections s
                LEFT JOIN documents d ON s.doc_id = d.doc_id
                WHERE d.doc_id IS NULL
            """,
            "clauses_orphans": """
                SELECT COUNT(*) FROM clauses c
                LEFT JOIN documents d ON c.doc_id = d.doc_id
                WHERE d.doc_id IS NULL
            """,
            "definitions_orphans": """
                SELECT COUNT(*) FROM definitions df
                LEFT JOIN documents d ON df.doc_id = d.doc_id
                WHERE d.doc_id IS NULL
            """,
            "section_text_orphans": """
                SELECT COUNT(*) FROM section_text st
                LEFT JOIN documents d ON st.doc_id = d.doc_id
                WHERE d.doc_id IS NULL
            """,
        }
        # Add orphan checks for feature tables if they exist
        if _table_exists(conn, "section_features"):
            orphan_checks["section_features_orphans"] = """
                SELECT COUNT(*) FROM section_features sf
                LEFT JOIN documents d ON sf.doc_id = d.doc_id
                WHERE d.doc_id IS NULL
            """
        if _table_exists(conn, "clause_features"):
            orphan_checks["clause_features_orphans"] = """
                SELECT COUNT(*) FROM clause_features cf
                LEFT JOIN documents d ON cf.doc_id = d.doc_id
                WHERE d.doc_id IS NULL
            """
        for check_name, query in orphan_checks.items():
            orphan_rows = _count(conn, query)
            report["checks"][check_name] = orphan_rows
            if orphan_rows > 0:
                report["errors"].append(f"{check_name}: {orphan_rows} orphan rows")

        key_null_checks = {
            "documents_doc_id_null_or_blank": """
                SELECT COUNT(*) FROM documents
                WHERE doc_id IS NULL OR TRIM(doc_id) = ''
            """,
            "sections_key_null_or_blank": """
                SELECT COUNT(*) FROM sections
                WHERE doc_id IS NULL OR TRIM(doc_id) = ''
                   OR section_number IS NULL OR TRIM(section_number) = ''
            """,
            "clauses_key_null_or_blank": """
                SELECT COUNT(*) FROM clauses
                WHERE doc_id IS NULL OR TRIM(doc_id) = ''
                   OR section_number IS NULL OR TRIM(section_number) = ''
                   OR clause_id IS NULL OR TRIM(clause_id) = ''
            """,
            "section_text_key_null_or_blank": """
                SELECT COUNT(*) FROM section_text
                WHERE doc_id IS NULL OR TRIM(doc_id) = ''
                   OR section_number IS NULL OR TRIM(section_number) = ''
            """,
            "definitions_key_null_or_blank": """
                SELECT COUNT(*) FROM definitions
                WHERE doc_id IS NULL OR TRIM(doc_id) = ''
                   OR term IS NULL OR TRIM(term) = ''
            """,
        }
        for check_name, query in key_null_checks.items():
            bad_rows = _count(conn, query)
            report["checks"][check_name] = bad_rows
            if bad_rows > 0:
                report["errors"].append(f"{check_name}: {bad_rows} invalid rows")

        docs_count = _count(conn, "SELECT COUNT(*) FROM documents")
        sections_count = _count(conn, "SELECT COUNT(*) FROM sections")
        clauses_count = _count(conn, "SELECT COUNT(*) FROM clauses")
        report["checks"]["documents_row_count"] = docs_count
        report["checks"]["sections_row_count"] = sections_count
        report["checks"]["clauses_row_count"] = clauses_count

        if docs_count == 0:
            report["errors"].append("documents table is empty")
        if sections_count < docs_count:
            report["warnings"].append(
                "sections row count is lower than documents row count"
            )
        if clauses_count == 0:
            report["warnings"].append("clauses table is empty")

        if checkpoint_path is not None and checkpoint_path.exists():
            ckpt = _load_json(checkpoint_path.read_bytes())
            if isinstance(ckpt, dict):
                total_processed = ckpt.get("total_processed")
                if not isinstance(total_processed, int):
                    processed_keys = ckpt.get("processed_doc_keys", [])
                    if isinstance(processed_keys, list):
                        total_processed = len(processed_keys)
                if isinstance(total_processed, int):
                    report["checks"]["checkpoint_total_processed"] = total_processed
                    if total_processed < docs_count:
                        report["errors"].append(
                            "checkpoint total_processed is less than documents row count"
                        )
                    elif total_processed > docs_count:
                        report["warnings"].append(
                            "checkpoint total_processed exceeds documents row count "
                            "(doc_id dedup collisions likely)"
                        )

        if report["errors"]:
            report["status"] = "fail"
        elif report["warnings"]:
            report["status"] = "warn"
    finally:
        conn.close()

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a corpus.duckdb built by build_corpus_ray_v2.py",
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to corpus.duckdb",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Optional checkpoint JSON for cross-checks",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional output file for gate report JSON",
    )
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="Exit non-zero on warnings as well as errors",
    )
    args = parser.parse_args()

    db_path = args.db.resolve()
    if not db_path.exists():
        print(f"ERROR: DB file not found: {db_path}", file=sys.stderr)
        sys.exit(2)

    checkpoint_path = args.checkpoint.resolve() if args.checkpoint else None
    report = _validate(db_path, checkpoint_path)

    payload = _dump_json(report)
    print(payload.decode("utf-8"))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_bytes(payload)

    if report["status"] == "fail":
        sys.exit(1)
    if report["status"] == "warn" and args.fail_on_warnings:
        sys.exit(1)


if __name__ == "__main__":
    main()
