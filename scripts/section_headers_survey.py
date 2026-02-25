#!/usr/bin/env python3
"""Broad-range survey of section headings across the corpus.

Queries the DuckDB corpus index for all distinct section headings,
groups by frequency, identifies the long tail, categorizes formats,
and builds a heading taxonomy.

Usage:
    python3 scripts/section_headers_survey.py --db corpus_index/corpus.duckdb
    python3 scripts/section_headers_survey.py --db corpus_index/corpus.duckdb --top 100

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
# Heading classification
# ---------------------------------------------------------------------------


def classify_heading(heading: str) -> str:
    """Classify a section heading into a category.

    Categories:
    - covenant: Negative/affirmative covenant headings
    - definition: Definition-related headings
    - financial: Financial covenant headings
    - event_of_default: EoD-related headings
    - representation: Representations and warranties
    - condition: Conditions precedent
    - facility: Facility/commitment headings
    - payment: Payment/prepayment headings
    - reserved: [Reserved] sections
    - other: Everything else
    """
    h = heading.strip().lower()

    if re.search(r"\[reserved\]|\[intentionally omitted\]", h):
        return "reserved"
    if re.search(r"defin|interpret|accounting terms", h):
        return "definition"
    if re.search(r"indebtedness|lien|restricted payment|merger|consolidat|invest|asset sale|affiliate|dividend", h):
        return "covenant"
    if re.search(r"financial covenant|leverage|coverage|interest coverage|fixed charge", h):
        return "financial"
    if re.search(r"event.?of.?default|default|cross.?default|acceleration", h):
        return "event_of_default"
    if re.search(r"represent|warrant", h):
        return "representation"
    if re.search(r"condition|precedent", h):
        return "condition"
    if re.search(r"commit|facility|loan|borrow|credit|tranche|incremental", h):
        return "facility"
    if re.search(r"prepay|repay|amortiz|mandatory.*payment|voluntary.*payment", h):
        return "payment"

    return "other"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Broad-range survey of section headings across the corpus."
    )
    parser.add_argument(
        "--db", type=Path, required=True,
        help="Path to DuckDB corpus index",
    )
    parser.add_argument(
        "--top", type=int, default=200,
        help="Show top N headings by frequency",
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

    # Query all distinct headings with counts
    rows = con.execute("""
        SELECT heading, COUNT(*) as cnt, COUNT(DISTINCT doc_id) as n_docs
        FROM sections
        WHERE heading IS NOT NULL AND heading != ''
        GROUP BY heading
        ORDER BY cnt DESC
    """).fetchall()

    # Total sections
    total_sections = con.execute(
        "SELECT COUNT(*) FROM sections"
    ).fetchone()
    total = total_sections[0] if total_sections else 0

    # Total unique headings
    unique_count = len(rows)

    # Total documents
    total_docs = con.execute(
        "SELECT COUNT(*) FROM documents WHERE cohort_included = true"
    ).fetchone()
    n_docs = total_docs[0] if total_docs else 0

    con.close()

    log(f"Section Headers Survey:")
    log(f"  Total sections: {total}")
    log(f"  Unique headings: {unique_count}")
    log(f"  Documents: {n_docs}")

    # Build heading distribution
    heading_counts: Counter[str] = Counter()
    heading_doc_counts: dict[str, int] = {}
    for heading, cnt, n_doc in rows:
        norm = heading.strip()
        heading_counts[norm] += cnt
        heading_doc_counts[norm] = heading_doc_counts.get(norm, 0) + n_doc

    # Classify headings
    category_counts: Counter[str] = Counter()
    classified_headings: list[dict[str, Any]] = []

    for heading, count in heading_counts.most_common(args.top):
        cat = classify_heading(heading)
        category_counts[cat] += 1
        classified_headings.append({
            "heading": heading,
            "count": count,
            "n_docs": heading_doc_counts.get(heading, 0),
            "category": cat,
            "prevalence": round(heading_doc_counts.get(heading, 0) / n_docs, 4) if n_docs > 0 else 0,
        })

    # Long tail analysis
    singleton_count = sum(1 for _, cnt in heading_counts.items() if cnt == 1)
    rare_count = sum(1 for _, cnt in heading_counts.items() if cnt <= 5)

    log(f"  Singletons (count=1): {singleton_count} ({singleton_count / unique_count * 100:.1f}%)")
    log(f"  Rare (count≤5): {rare_count} ({rare_count / unique_count * 100:.1f}%)")
    log(f"  Categories: {dict(category_counts.most_common())}")

    output = {
        "total_sections": total,
        "unique_headings": unique_count,
        "total_documents": n_docs,
        "singleton_headings": singleton_count,
        "rare_headings": rare_count,
        "category_distribution": dict(category_counts.most_common()),
        "top_headings": classified_headings,
    }

    dump_json(output)


if __name__ == "__main__":
    main()
