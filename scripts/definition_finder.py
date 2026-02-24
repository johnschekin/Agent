#!/usr/bin/env python3
"""Extract defined terms from a document in the corpus index.

Usage:
    python3 scripts/definition_finder.py --db corpus_index/corpus.duckdb --doc-id abc123
    python3 scripts/definition_finder.py --db corpus_index/corpus.duckdb \
      --doc-id abc123 --term "Consolidated EBITDA"

Outputs structured JSON to stdout, human messages to stderr.
"""

import argparse
import json
import sys
from pathlib import Path

from agent.corpus import SchemaVersionError, ensure_schema_version
from agent.definition_graph import build_definition_dependency_graph
from agent.definition_types import classify_definition_records
from agent.definitions import infer_dependency_terms

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract defined terms from a document."
    )
    parser.add_argument(
        "--db", required=True, help="Path to corpus.duckdb"
    )
    parser.add_argument(
        "--doc-id", required=True, help="Document ID"
    )
    parser.add_argument(
        "--term", default=None, help="Find a specific term"
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Disable definition type/dependency enrichment in output.",
    )
    parser.add_argument(
        "--with-graph-summary",
        action="store_true",
        help="Emit definition dependency graph summary alongside records.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        log(f"Error: database not found at {db_path}")
        sys.exit(1)

    try:
        import duckdb
    except ImportError:
        log("Error: duckdb package is required. Install with: pip install duckdb")
        sys.exit(1)

    log(f"Opening corpus database: {db_path}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        ensure_schema_version(con, db_path=db_path)
    except SchemaVersionError as exc:
        log(f"Error: {exc}")
        con.close()
        sys.exit(1)

    if not args.include_all:
        cohort_row = con.execute(
            "SELECT cohort_included FROM documents WHERE doc_id = ?",
            [args.doc_id],
        ).fetchone()
        if cohort_row is None:
            log(f"Error: document not found: {args.doc_id}")
            con.close()
            sys.exit(1)
        if not bool(cohort_row[0]):
            log(
                f"Error: document {args.doc_id} is excluded from cohort. "
                "Use --include-all to query anyway."
            )
            con.close()
            sys.exit(1)

    # Check available tables to find definitions
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    log(f"Available tables: {tables}")

    # Try to find definitions table — adapt to actual schema
    definitions_table = None
    for candidate in ["definitions", "defined_terms", "terms", "definition"]:
        if candidate in tables:
            definitions_table = candidate
            break

    results: list[dict] = []

    if definitions_table:
        log(f"Using definitions table: {definitions_table}")

        # Get column names to adapt query
        columns_info = con.execute(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{definitions_table}'"
        ).fetchall()
        columns = [row[0] for row in columns_info]
        log(f"Columns: {columns}")

        # Build query based on available columns
        doc_id_col = next(
            (c for c in columns if c in ("doc_id", "document_id", "id")), None
        )
        term_col = next(
            (c for c in columns if c in ("term", "defined_term", "term_name")), None
        )
        text_col = next(
            (c for c in columns if c in ("definition_text", "text", "definition", "def_text")),
            None,
        )
        start_col = next(
            (c for c in columns if c in ("char_start", "start_offset", "span_start")),
            None,
        )
        end_col = next(
            (c for c in columns if c in ("char_end", "end_offset", "span_end")), None
        )
        engine_col = next(
            (c for c in columns if c in ("pattern_engine", "engine", "method")), None
        )
        conf_col = next(
            (c for c in columns if c in ("confidence", "score", "conf")), None
        )
        type_col = next(
            (c for c in columns if c in ("definition_type", "type", "def_type")),
            None,
        )
        types_col = next(
            (c for c in columns if c in ("definition_types", "type_list")),
            None,
        )
        type_conf_col = next(
            (c for c in columns if c in ("type_confidence", "def_type_confidence")),
            None,
        )
        type_sig_col = next(
            (c for c in columns if c in ("type_signals", "def_type_signals")),
            None,
        )
        deps_col = next(
            (c for c in columns if c in ("dependency_terms", "definition_dependencies")),
            None,
        )

        if not doc_id_col:
            log(f"Error: no doc_id column found in {definitions_table}. Columns: {columns}")
            sys.exit(1)

        # Build SELECT clause
        select_parts = []
        if term_col:
            select_parts.append(f"{term_col} AS term")
        if text_col:
            select_parts.append(f"{text_col} AS definition_text")
        if start_col:
            select_parts.append(f"{start_col} AS char_start")
        if end_col:
            select_parts.append(f"{end_col} AS char_end")
        if engine_col:
            select_parts.append(f"{engine_col} AS pattern_engine")
        if conf_col:
            select_parts.append(f"{conf_col} AS confidence")
        if type_col:
            select_parts.append(f"{type_col} AS definition_type")
        if types_col:
            select_parts.append(f"{types_col} AS definition_types")
        if type_conf_col:
            select_parts.append(f"{type_conf_col} AS type_confidence")
        if type_sig_col:
            select_parts.append(f"{type_sig_col} AS type_signals")
        if deps_col:
            select_parts.append(f"{deps_col} AS dependency_terms")

        if not select_parts:
            select_parts.append("*")

        select_clause = ", ".join(select_parts)

        # Build WHERE clause
        where_parts = [f"{doc_id_col} = ?"]
        params: list[object] = [args.doc_id]

        if args.term and term_col:
            where_parts.append(f"LOWER({term_col}) = LOWER(?)")
            params.append(args.term)

        where_clause = " AND ".join(where_parts)

        query = f"SELECT {select_clause} FROM {definitions_table} WHERE {where_clause}"
        log(f"Query: {query}")

        rows = con.execute(query, params).fetchall()
        col_names = [desc[0] for desc in con.description]

        for row in rows:
            record = dict(zip(col_names, row, strict=True))
            # Ensure standard field names with defaults
            results.append({
                "term": record.get("term", ""),
                "definition_text": record.get("definition_text", ""),
                "char_start": record.get("char_start"),
                "char_end": record.get("char_end"),
                "pattern_engine": record.get("pattern_engine", "unknown"),
                "confidence": record.get("confidence"),
                "definition_type": record.get("definition_type"),
                "definition_types": record.get("definition_types"),
                "type_confidence": record.get("type_confidence"),
                "type_signals": record.get("type_signals"),
                "dependency_terms": record.get("dependency_terms"),
            })

        log(f"Found {len(results)} definition(s)")

    else:
        # Fallback: try querying sections/clauses for definition patterns
        log("No dedicated definitions table found. Attempting section-based extraction.")

        sections_table = None
        for candidate in ["sections", "clauses", "paragraphs", "content"]:
            if candidate in tables:
                sections_table = candidate
                break

        if not sections_table:
            log(f"Error: no usable table found. Available: {tables}")
            sys.exit(1)

        columns_info = con.execute(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{sections_table}'"
        ).fetchall()
        columns = [row[0] for row in columns_info]
        log(f"Using table '{sections_table}' with columns: {columns}")

        doc_id_col = next(
            (c for c in columns if c in ("doc_id", "document_id", "id")), None
        )
        text_col = next(
            (c for c in columns if c in ("text", "content", "body", "section_text")),
            None,
        )

        if not doc_id_col or not text_col:
            log("Error: cannot find doc_id and text columns")
            sys.exit(1)

        import re

        # Patterns for defined terms: "Term" means ..., "Term" shall mean ...
        definition_patterns = [
            re.compile(
                r'"([^"]{2,80})"\s+(?:means?|shall\s+mean|is\s+defined\s+as|refers?\s+to)\s+(.{20,500}?)(?:\.|;|\n)',
                re.IGNORECASE,
            ),
            re.compile(
                r'\u201c([^\u201d]{2,80})\u201d\s+(?:means?|shall\s+mean|is\s+defined\s+as|refers?\s+to)\s+(.{20,500}?)(?:\.|;|\n)',
                re.IGNORECASE,
            ),
        ]

        query = f"SELECT {text_col} FROM {sections_table} WHERE {doc_id_col} = ?"
        params_list: list[object] = [args.doc_id]
        rows = con.execute(query, params_list).fetchall()

        for row in rows:
            text = row[0] or ""
            for pattern in definition_patterns:
                for match in pattern.finditer(text):
                    term_name = match.group(1)
                    def_text = match.group(2).strip()

                    if args.term and args.term.lower() != term_name.lower():
                        continue

                    results.append({
                        "term": term_name,
                        "definition_text": def_text,
                        "char_start": match.start(),
                        "char_end": match.end(),
                        "pattern_engine": "quoted",
                        "confidence": 0.85,
                        "definition_type": None,
                        "definition_types": None,
                        "type_confidence": None,
                        "type_signals": None,
                        "dependency_terms": None,
                    })

        # Deduplicate by term
        seen: set[str] = set()
        deduped: list[dict] = []
        for r in results:
            key = r["term"].lower()
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        results = deduped
        log(f"Extracted {len(results)} definition(s) via pattern matching")

    if not args.no_enrich and results:
        results = classify_definition_records(results)
        for record in results:
            if not record.get("dependency_terms"):
                record["dependency_terms"] = list(
                    infer_dependency_terms(
                        str(record.get("definition_text") or ""),
                        term_name=str(record.get("term") or ""),
                    )
                )
            if not record.get("definition_type"):
                record["definition_type"] = "DIRECT"
            if not isinstance(record.get("definition_types"), list):
                record["definition_types"] = [record["definition_type"]]
            if not isinstance(record.get("type_signals"), list):
                record["type_signals"] = []
            if record.get("type_confidence") is None:
                record["type_confidence"] = 0.5

    con.close()
    if args.with_graph_summary:
        dump_json(
            {
                "definitions": results,
                "definition_graph": build_definition_dependency_graph(results),
            }
        )
        return
    dump_json(results)


if __name__ == "__main__":
    main()
