#!/usr/bin/env python3
"""Corpus-wide numbering format taxonomy census.

Classifies each document's article and section numbering conventions:
- Article format: ROMAN / ARABIC / SECTION_ONLY / HYBRID
- Section depth: 2-level (X.YY) / 3-level (X.YY.ZZ)
- Zero-padding: true/false
- Mid-document anomalies: mixed numbering within a document

Usage:
    python3 scripts/numbering_census.py --db corpus_index/corpus.duckdb
    python3 scripts/numbering_census.py --db corpus_index/corpus.duckdb --sample 500

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import orjson

    def dump_json(obj: Any) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: Any) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------

_ROMAN_RE = re.compile(r"^[IVXLCDM]+$")
_ZERO_PADDED_RE = re.compile(r"^\d+\.0\d+$")
_THREE_LEVEL_RE = re.compile(r"^\d+\.\d+\.\d+$")


def classify_article_format(section_numbers: list[str]) -> str:
    """Classify article format from section numbers.

    Returns: ROMAN | ARABIC | SECTION_ONLY | HYBRID
    """
    if not section_numbers:
        return "SECTION_ONLY"

    majors = set()
    for num in section_numbers:
        parts = num.split(".")
        if parts:
            majors.add(parts[0])

    # Check if any major is roman
    has_roman = any(_ROMAN_RE.match(m) for m in majors)
    has_arabic = any(m.isdigit() for m in majors)

    if has_roman and has_arabic:
        return "HYBRID"
    if has_roman:
        return "ROMAN"
    if has_arabic:
        return "ARABIC"
    return "SECTION_ONLY"


def classify_section_depth(section_numbers: list[str]) -> int:
    """Classify section depth: 2 (X.YY) or 3 (X.YY.ZZ)."""
    for num in section_numbers:
        if _THREE_LEVEL_RE.match(num):
            return 3
    return 2


def detect_zero_padding(section_numbers: list[str]) -> bool:
    """Detect if sections use zero-padding (7.01 vs 7.1)."""
    padded = sum(1 for n in section_numbers if _ZERO_PADDED_RE.match(n))
    return padded > len(section_numbers) * 0.5


def detect_anomalies(section_numbers: list[str]) -> list[str]:
    """Detect mid-document numbering anomalies."""
    anomalies: list[str] = []

    if not section_numbers:
        return anomalies

    # Check for mixed zero-padding within document
    padded = sum(1 for n in section_numbers if _ZERO_PADDED_RE.match(n))
    unpadded = len(section_numbers) - padded
    if padded > 0 and unpadded > 0 and min(padded, unpadded) > 2:
        anomalies.append("mixed_zero_padding")

    # Check for non-monotonic major numbers (article jumping)
    majors: list[int] = []
    for num in section_numbers:
        parts = num.split(".")
        if parts and parts[0].isdigit():
            majors.append(int(parts[0]))
    if majors:
        for i in range(1, len(majors)):
            if majors[i] < majors[i - 1] - 1:  # Allow minor decreases
                anomalies.append("non_monotonic_articles")
                break

    return anomalies


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Corpus-wide numbering format taxonomy census."
    )
    parser.add_argument(
        "--db", type=Path, required=True,
        help="Path to DuckDB corpus index",
    )
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Limit to N documents (0 = all)",
    )
    args = parser.parse_args()

    try:
        import duckdb
    except ImportError:
        log("ERROR: duckdb not installed")
        sys.exit(1)

    if not args.db.exists():
        log(f"ERROR: corpus index not found at {args.db}")
        sys.exit(1)

    con = duckdb.connect(str(args.db), read_only=True)

    # Get document list
    limit_clause = f"LIMIT {args.sample}" if args.sample > 0 else ""
    doc_ids = [
        r[0] for r in con.execute(
            f"SELECT doc_id FROM documents WHERE cohort_included = true {limit_clause}"
        ).fetchall()
    ]
    log(f"Processing {len(doc_ids)} documents...")

    # Fetch all sections in bulk
    sections = con.execute(
        "SELECT doc_id, section_number FROM sections ORDER BY doc_id, section_number"
    ).fetchall()
    con.close()

    # Group sections by doc_id
    doc_sections: dict[str, list[str]] = {}
    for doc_id, sec_num in sections:
        doc_sections.setdefault(doc_id, []).append(sec_num)

    # Classify each document
    format_counts: Counter[str] = Counter()
    depth_counts: Counter[int] = Counter()
    padding_counts: Counter[str] = Counter()
    anomaly_counts: Counter[str] = Counter()
    doc_results: list[dict[str, Any]] = []

    for doc_id in doc_ids:
        sec_nums = doc_sections.get(doc_id, [])
        art_format = classify_article_format(sec_nums)
        depth = classify_section_depth(sec_nums)
        zero_pad = detect_zero_padding(sec_nums)
        anomalies = detect_anomalies(sec_nums)

        format_counts[art_format] += 1
        depth_counts[depth] += 1
        padding_counts["zero_padded" if zero_pad else "not_padded"] += 1
        for a in anomalies:
            anomaly_counts[a] += 1

        doc_results.append({
            "doc_id": doc_id,
            "section_count": len(sec_nums),
            "article_format": art_format,
            "section_depth": depth,
            "zero_padded": zero_pad,
            "anomalies": anomalies,
        })

    # Summary
    total = len(doc_ids)
    log(f"\nNumbering Format Census ({total} documents):")
    log(f"  Article format: {dict(format_counts.most_common())}")
    log(f"  Section depth: {dict(depth_counts.most_common())}")
    log(f"  Zero-padding: {dict(padding_counts.most_common())}")
    log(f"  Anomalies: {dict(anomaly_counts.most_common())}")

    output = {
        "total_documents": total,
        "format_distribution": dict(format_counts.most_common()),
        "depth_distribution": {str(k): v for k, v in depth_counts.most_common()},
        "padding_distribution": dict(padding_counts.most_common()),
        "anomaly_distribution": dict(anomaly_counts.most_common()),
        "documents": doc_results,
    }

    dump_json(output)


if __name__ == "__main__":
    main()
