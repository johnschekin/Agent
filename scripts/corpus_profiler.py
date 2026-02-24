#!/usr/bin/env python3
"""Build a machine-readable profile of corpus index quality and composition.

Usage:
    python3 scripts/corpus_profiler.py --db corpus_index/corpus.duckdb \
      --output corpus_index/corpus_profile.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from agent.corpus import SchemaVersionError, ensure_schema_version
from agent.run_manifest import (
    compare_manifests,
    default_manifest_path_for_db,
    load_manifest,
)

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def write_json(path: Path, obj: object) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def write_json(path: Path, obj: object) -> None:
        path.write_text(json.dumps(obj, indent=2, default=str))


try:
    import duckdb
except ImportError:
    print("Error: duckdb is required. Install with: pip install duckdb", file=sys.stderr)
    sys.exit(1)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] * (hi - k) + s[hi] * (k - lo)


def _metric_stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p5": 0.0,
            "p95": 0.0,
        }
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 3),
        "median": round(_median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "p5": round(_percentile(values, 0.05), 3),
        "p95": round(_percentile(values, 0.95), 3),
    }


def _count_map(con: Any, sql: str, params: list[object] | None = None) -> dict[str, int]:
    rows = con.execute(sql, params or []).fetchall()
    return {str(r[0]) if r[0] is not None else "unknown": int(r[1]) for r in rows}


def _derive_failure_signatures(
    *,
    section_count: int,
    clause_count: int,
    word_count: int,
    text_length: int,
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
    if not signatures:
        signatures.append("none")
    return signatures


def _anomaly_details(
    con: Any,
    *,
    where_sql: str,
    limit: int,
) -> list[dict[str, Any]]:
    doc_columns = {
        str(r[0])
        for r in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'documents'
            """
        ).fetchall()
    }
    template_expr = "template_family" if "template_family" in doc_columns else "'unknown'"
    definition_count_expr = (
        "definition_count" if "definition_count" in doc_columns else "0"
    )
    word_count_expr = "word_count" if "word_count" in doc_columns else "0"
    text_length_expr = "text_length" if "text_length" in doc_columns else "0"
    rows = con.execute(
        f"""
        SELECT doc_id, {template_expr} AS template_family, section_count, clause_count,
               {definition_count_expr}, {word_count_expr}, {text_length_expr}
        FROM documents
        WHERE {where_sql}
        ORDER BY template_family, doc_id
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        section_count = int(row[2] or 0)
        clause_count = int(row[3] or 0)
        word_count = int(row[5] or 0)
        text_length = int(row[6] or 0)
        out.append(
            {
                "doc_id": str(row[0] or ""),
                "template_family": str(row[1] or "unknown"),
                "section_count": section_count,
                "clause_count": clause_count,
                "definition_count": int(row[4] or 0),
                "word_count": word_count,
                "text_length": text_length,
                "failure_signatures": _derive_failure_signatures(
                    section_count=section_count,
                    clause_count=clause_count,
                    word_count=word_count,
                    text_length=text_length,
                ),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate corpus profile JSON.")
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument(
        "--output",
        default="corpus_index/corpus_profile.json",
        help="Output profile JSON path",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents in distribution stats.",
    )
    parser.add_argument(
        "--anomaly-limit",
        type=int,
        default=200,
        help="Max anomaly document IDs to include per category.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "Optional run manifest path. Defaults to sidecar run_manifest.json "
            "next to --db if present."
        ),
    )
    parser.add_argument(
        "--compare-manifest",
        default=None,
        help="Optional second manifest path for deterministic snapshot diff.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        _log(f"Error: database not found at {db_path}")
        sys.exit(1)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        ensure_schema_version(con, db_path=db_path)
    except SchemaVersionError as exc:
        _log(f"Error: {exc}")
        con.close()
        sys.exit(1)

    global_counts = con.execute(
        """
        SELECT
            COUNT(*) AS total_docs,
            SUM(CASE WHEN cohort_included THEN 1 ELSE 0 END) AS cohort_docs,
            SUM(CASE WHEN section_count > 0 THEN 1 ELSE 0 END) AS docs_with_sections,
            SUM(CASE WHEN definition_count > 0 THEN 1 ELSE 0 END) AS docs_with_definitions,
            SUM(CASE WHEN clause_count > 0 THEN 1 ELSE 0 END) AS docs_with_clauses
        FROM documents
        """
    ).fetchone()

    total_docs = int(global_counts[0] or 0)
    cohort_docs = int(global_counts[1] or 0)
    docs_with_sections = int(global_counts[2] or 0)
    docs_with_definitions = int(global_counts[3] or 0)
    docs_with_clauses = int(global_counts[4] or 0)

    target_where = "" if args.include_all else "WHERE cohort_included = true"
    metric_rows = con.execute(
        f"""
        SELECT
            word_count, section_count, clause_count, definition_count, facility_size_mm
        FROM documents
        {target_where}
        """
    ).fetchall()

    word_counts = [float(r[0]) for r in metric_rows if r[0] is not None]
    section_counts = [float(r[1]) for r in metric_rows if r[1] is not None]
    clause_counts = [float(r[2]) for r in metric_rows if r[2] is not None]
    definition_counts = [float(r[3]) for r in metric_rows if r[3] is not None]
    facility_sizes = [float(r[4]) for r in metric_rows if r[4] is not None]

    by_doc_type = _count_map(
        con,
        "SELECT doc_type, COUNT(*) FROM documents GROUP BY doc_type ORDER BY COUNT(*) DESC",
    )
    by_market_segment = _count_map(
        con,
        (
            "SELECT market_segment, COUNT(*) FROM documents "
            "GROUP BY market_segment ORDER BY COUNT(*) DESC"
        ),
    )
    by_template_family = _count_map(
        con,
        (
            "SELECT template_family, COUNT(*) FROM documents "
            "GROUP BY template_family ORDER BY COUNT(*) DESC"
        ),
    )

    anomaly_limit = max(1, args.anomaly_limit)
    no_sections = [
        str(r[0])
        for r in con.execute(
            "SELECT doc_id FROM documents WHERE section_count = 0 ORDER BY doc_id LIMIT ?",
            [anomaly_limit],
        ).fetchall()
    ]
    no_definitions = [
        str(r[0])
        for r in con.execute(
            "SELECT doc_id FROM documents WHERE definition_count = 0 ORDER BY doc_id LIMIT ?",
            [anomaly_limit],
        ).fetchall()
    ]
    no_sections_details = _anomaly_details(
        con,
        where_sql="section_count = 0",
        limit=anomaly_limit,
    )
    zero_clauses_details = _anomaly_details(
        con,
        where_sql="clause_count = 0",
        limit=anomaly_limit,
    )

    section_success_rate = (
        round((docs_with_sections / total_docs), 4)
        if total_docs
        else 0.0
    )
    definition_success_rate = (
        round((docs_with_definitions / total_docs), 4)
        if total_docs
        else 0.0
    )
    clause_success_rate = (
        round((docs_with_clauses / total_docs), 4)
        if total_docs
        else 0.0
    )
    zero_clauses = [
        str(r[0])
        for r in con.execute(
            "SELECT doc_id FROM documents WHERE clause_count = 0 ORDER BY doc_id LIMIT ?",
            [anomaly_limit],
        ).fetchall()
    ]

    manifest_path = (
        Path(args.manifest).resolve()
        if args.manifest
        else default_manifest_path_for_db(db_path).resolve()
    )
    manifest_payload: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            manifest_payload = load_manifest(manifest_path)
        except Exception as exc:
            _log(f"Warning: failed to read manifest {manifest_path}: {exc}")

    manifest_compare_payload: dict[str, Any] | None = None
    if args.compare_manifest:
        cmp_path = Path(args.compare_manifest).resolve()
        if not cmp_path.exists():
            _log(f"Warning: compare manifest not found: {cmp_path}")
        else:
            try:
                previous_manifest = load_manifest(cmp_path)
                if manifest_payload is None:
                    _log(
                        "Warning: comparison requested but primary manifest is missing."
                    )
                else:
                    manifest_compare_payload = compare_manifests(
                        manifest_payload,
                        previous_manifest,
                    )
                    manifest_compare_payload["current_manifest_path"] = str(manifest_path)
                    manifest_compare_payload["previous_manifest_path"] = str(cmp_path)
            except Exception as exc:
                _log(f"Warning: failed to compare manifests: {exc}")

    profile: dict[str, Any] = {
        "schema_version": str(
            con.execute(
                "SELECT version FROM _schema_version WHERE table_name = 'corpus'"
            ).fetchone()[0]
        ),
        "counts": {
            "total_docs": total_docs,
            "cohort_docs": cohort_docs,
            "excluded_docs": max(0, total_docs - cohort_docs),
        },
        "parse_quality": {
            "docs_with_sections": docs_with_sections,
            "docs_with_definitions": docs_with_definitions,
            "docs_with_clauses": docs_with_clauses,
            "section_success_rate": section_success_rate,
            "definition_success_rate": definition_success_rate,
            "clause_success_rate": clause_success_rate,
        },
        "distributions": {
            "by_doc_type": by_doc_type,
            "by_market_segment": by_market_segment,
            "by_template_family": by_template_family,
            "word_count": _metric_stats(word_counts),
            "section_count": _metric_stats(section_counts),
            "clause_count": _metric_stats(clause_counts),
            "definition_count": _metric_stats(definition_counts),
            "facility_size_mm": _metric_stats(facility_sizes),
        },
        "anomalies": {
            "no_sections": no_sections,
            "no_sections_details": no_sections_details,
            "no_definitions": no_definitions,
            "zero_clauses": zero_clauses,
            "zero_clauses_details": zero_clauses_details,
            "limit_per_list": anomaly_limit,
        },
        "manifest": {
            "path": str(manifest_path),
            "present": manifest_payload is not None,
            "run_id": manifest_payload.get("run_id") if manifest_payload else None,
            "created_at": manifest_payload.get("created_at") if manifest_payload else None,
            "manifest_version": (
                manifest_payload.get("manifest_version")
                if manifest_payload
                else None
            ),
        },
    }
    if manifest_compare_payload is not None:
        profile["manifest_comparison"] = manifest_compare_payload

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(out_path, profile)
    con.close()

    dump_json(
        {
            "status": "ok",
            "output_path": str(out_path),
            "total_docs": total_docs,
            "cohort_docs": cohort_docs,
            "manifest_present": manifest_payload is not None,
            "manifest_path": str(manifest_path),
        }
    )


if __name__ == "__main__":
    main()
