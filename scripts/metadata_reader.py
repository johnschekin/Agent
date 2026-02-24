#!/usr/bin/env python3
"""Query corpus metadata.

Provides per-document metadata lookup, filtered queries using SQL WHERE
clauses, and corpus-level statistics.

Usage:
    # Get metadata for a specific document
    python3 scripts/metadata_reader.py --db corpus_index/corpus.duckdb --doc-id abc123

    # Filter documents by SQL WHERE clause
    python3 scripts/metadata_reader.py --db corpus_index/corpus.duckdb \
      --filter "admin_agent ILIKE '%JPMorgan%'" --limit 20

    # Show corpus-level statistics
    python3 scripts/metadata_reader.py --db corpus_index/corpus.duckdb --stats
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


from agent.corpus import CorpusIndex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query corpus metadata."
    )
    parser.add_argument(
        "--db", required=True, type=Path, help="Path to corpus.duckdb"
    )
    parser.add_argument(
        "--doc-id", default=None, help="Get metadata for a specific document"
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="SQL WHERE clause to filter documents (e.g., \"admin_agent ILIKE '%%JPMorgan%%'\")",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum results for filter mode (default: 20)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show corpus-level statistics",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    return parser


def _doc_to_dict(doc: Any) -> dict[str, object]:
    """Convert a DocRecord to a JSON-serializable dict."""
    return {
        "doc_id": doc.doc_id,
        "cik": doc.cik,
        "accession": doc.accession,
        "borrower": doc.borrower,
        "admin_agent": doc.admin_agent,
        "section_count": doc.section_count,
        "clause_count": doc.clause_count,
        "definition_count": doc.definition_count,
        "text_length": doc.text_length,
        "template_family": doc.template_family,
        "facility_size_mm": doc.facility_size_mm,
        "closing_date": doc.closing_date,
        "filing_date": doc.filing_date,
        "form_type": doc.form_type,
    }


def main() -> None:
    args = build_parser().parse_args()

    if not args.db.exists():
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    # Validate mutually exclusive modes
    modes = sum([
        args.doc_id is not None,
        args.filter is not None,
        args.stats,
    ])
    if modes == 0:
        print(
            "Error: specify one of --doc-id, --filter, or --stats",
            file=sys.stderr,
        )
        sys.exit(1)
    if modes > 1:
        print(
            "Error: --doc-id, --filter, and --stats are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(1)

    with CorpusIndex(args.db) as corpus:
        if args.doc_id is not None:
            # Single document mode
            doc = corpus.get_doc(args.doc_id)
            if doc is None:
                print(
                    f"Error: document not found: {args.doc_id}",
                    file=sys.stderr,
                )
                sys.exit(1)
            if not args.include_all and not doc.cohort_included:
                print(
                    f"Error: document {args.doc_id} is excluded from cohort; use --include-all",
                    file=sys.stderr,
                )
                sys.exit(1)

            result = _doc_to_dict(doc)
            print(
                f"Document {args.doc_id}: {doc.section_count} sections, "
                f"{doc.definition_count} definitions, "
                f"{doc.text_length:,} chars",
                file=sys.stderr,
            )
            dump_json(result)

        elif args.filter is not None:
            # Filter mode: use raw SQL query with user-provided WHERE clause
            base_where = "cohort_included = true"
            final_filter = args.filter if args.include_all else f"({base_where}) AND ({args.filter})"
            query = f"""
                SELECT doc_id, cik, accession, borrower, admin_agent,
                       section_count, clause_count, definition_count,
                       text_length, template_family, facility_size_mm,
                       closing_date, filing_date, form_type
                FROM documents
                WHERE {final_filter}
                LIMIT ?
            """
            try:
                rows = corpus.query(query, [args.limit])
            except Exception as e:
                print(f"Error executing filter query: {e}", file=sys.stderr)
                sys.exit(1)

            columns = [
                "doc_id", "cik", "accession", "borrower", "admin_agent",
                "section_count", "clause_count", "definition_count",
                "text_length", "template_family", "facility_size_mm",
                "closing_date", "filing_date", "form_type",
            ]
            results: list[dict[str, object]] = []
            for row in rows:
                record: dict[str, object] = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    # Convert to appropriate Python type
                    if val is None:
                        record[col] = None
                    elif isinstance(val, (int, float, bool)):
                        record[col] = val
                    else:
                        record[col] = str(val)
                results.append(record)

            print(
                f"Filter matched {len(results)} documents (limit: {args.limit})",
                file=sys.stderr,
            )
            dump_json(results)

        elif args.stats:
            # Stats mode: corpus-level aggregate statistics
            where = "" if args.include_all else " WHERE cohort_included = true"
            stats_query = """
                SELECT
                    COUNT(*) as total_documents,
                    SUM(section_count) as total_sections,
                    SUM(clause_count) as total_clauses,
                    SUM(definition_count) as total_definitions,
                    ROUND(AVG(section_count), 1) as avg_sections_per_doc,
                    ROUND(AVG(definition_count), 1) as avg_definitions_per_doc,
                    ROUND(AVG(text_length), 0) as avg_text_length,
                    MIN(text_length) as min_text_length,
                    MAX(text_length) as max_text_length
                FROM documents
            """ + where
            rows = corpus.query(stats_query)
            if not rows:
                print("Error: could not compute statistics", file=sys.stderr)
                sys.exit(1)

            row = rows[0]
            stats: dict[str, object] = {
                "total_documents": int(row[0]),
                "total_sections": int(row[1]) if row[1] else 0,
                "total_clauses": int(row[2]) if row[2] else 0,
                "total_definitions": int(row[3]) if row[3] else 0,
                "avg_sections_per_doc": float(row[4]) if row[4] else 0.0,
                "avg_definitions_per_doc": float(row[5]) if row[5] else 0.0,
                "avg_text_length": float(row[6]) if row[6] else 0.0,
                "min_text_length": int(row[7]) if row[7] else 0,
                "max_text_length": int(row[8]) if row[8] else 0,
            }

            # Also get template family distribution
            family_query = """
                SELECT template_family, COUNT(*) as count
                FROM documents
            """ + where + """
                GROUP BY template_family
                ORDER BY count DESC
            """
            family_rows = corpus.query(family_query)
            stats["template_families"] = {
                str(r[0]): int(r[1]) for r in family_rows
            }

            print(
                f"Corpus: {stats['total_documents']} documents, "
                f"{stats['total_sections']} sections, "
                f"{stats['total_definitions']} definitions",
                file=sys.stderr,
            )
            dump_json(stats)


if __name__ == "__main__":
    main()
