#!/usr/bin/env python3
"""Diagnose documents that produce zero sections through the parser pipeline.

Queries DuckDB for all section_count=0 docs, loads each HTML from corpus/,
runs it through the parser with instrumented checkpoints, and outputs a
structured JSON report with per-doc failure mode classification.

Usage::

    python3 scripts/diagnose_zero_sections.py \\
        --corpus-dir corpus/ \\
        --db corpus_index/corpus.duckdb

    # Spot-check random docs that DO have sections (regression check)
    python3 scripts/diagnose_zero_sections.py \\
        --corpus-dir corpus/ \\
        --db corpus_index/corpus.duckdb \\
        --all-docs --spot-check 200
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# JSON — prefer orjson, fall back to stdlib
# ---------------------------------------------------------------------------
try:
    import orjson

    def _json_dumps(obj: Any) -> str:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode()
except ImportError:
    import json

    def _json_dumps(obj: Any) -> str:  # type: ignore[misc]
        return json.dumps(obj, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Project imports — regexes and helpers from doc_parser (conventionally private
# but importable; avoids duplicating 6 regex patterns)
# ---------------------------------------------------------------------------
from agent.corpus import CorpusIndex  # noqa: I001
from agent.doc_parser import (  # type: ignore[attr-defined]
    DocOutline,
    _ARTICLE_RE,
    _ARTICLE_SPACED_RE,
    _ARTICLE_SPLIT_RE,
    _SECTION_BARE_RE,
    _SECTION_STRICT_RE,
    _SECTION_TOPLEVEL_RE,
    _is_toc_entry,
)
from agent.html_utils import normalize_html, read_file


# ---------------------------------------------------------------------------
# Failure mode classification
# ---------------------------------------------------------------------------

def _classify_failure(
    *,
    word_count: int,
    doc_type: str,
    raw_article_matches: int,
    raw_section_matches: int,
    toc_rejected_articles: int,
    toc_rejected_sections: int,
    final_section_count: int,
    text_length: int,
    non_ascii_ratio: float,
) -> str:
    """Auto-classify a zero-section doc into a failure mode bucket."""
    if word_count < 500:
        return "short_document"

    if doc_type not in ("credit_agreement", "other", ""):
        return "not_credit_agreement"

    total_raw = raw_article_matches + raw_section_matches
    total_toc_rejected = toc_rejected_articles + toc_rejected_sections

    # All raw matches existed but were TOC-rejected
    if total_raw > 0 and total_toc_rejected == total_raw:
        return "toc_over_rejection"

    # Had raw matches but all were rejected by ghost/plausibility/span filters
    if total_raw > 0 and final_section_count == 0:
        return "aggressive_filtering"

    # HTML artifacts: high non-ASCII or very short text relative to word count
    if non_ascii_ratio > 0.15 or (text_length > 0 and word_count / text_length < 0.05):
        return "html_artifact"

    # Zero matches for everything and a substantial document
    if total_raw == 0 and word_count > 5000:
        return "non_standard_headings"

    if total_raw == 0 and word_count <= 5000:
        return "short_document"

    return "unclassified"


def _non_ascii_ratio(text: str) -> float:
    """Fraction of characters outside printable ASCII range."""
    if not text:
        return 0.0
    count = sum(1 for ch in text if ord(ch) > 127)
    return count / len(text)


# ---------------------------------------------------------------------------
# Per-document diagnosis
# ---------------------------------------------------------------------------

def _diagnose_one(
    doc_id: str,
    html_path: Path,
    doc_type: str,
    db_word_count: int,
) -> dict[str, Any]:
    """Run instrumented parser checkpoints on a single document."""
    record: dict[str, Any] = {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "db_word_count": db_word_count,
        "html_path": str(html_path),
    }

    # Load and normalize HTML
    raw_html = read_file(html_path)
    if not raw_html:
        record["failure_mode"] = "html_read_failure"
        record["text_preview"] = ""
        return record

    text, _ = normalize_html(raw_html)
    record["text_length"] = len(text)
    record["word_count"] = len(text.split())
    record["text_preview"] = text[:500]
    record["non_ascii_ratio"] = round(_non_ascii_ratio(text), 4)

    # Run each regex individually and count raw + TOC-rejected matches
    regex_results: dict[str, dict[str, int]] = {}
    total_article_raw = 0
    total_article_toc = 0
    total_section_raw = 0
    total_section_toc = 0

    article_regexes = {
        "ARTICLE_RE": _ARTICLE_RE,
        "SECTION_TOPLEVEL_RE": _SECTION_TOPLEVEL_RE,
        "ARTICLE_SPACED_RE": _ARTICLE_SPACED_RE,
        "ARTICLE_SPLIT_RE": _ARTICLE_SPLIT_RE,
    }
    section_regexes = {
        "SECTION_STRICT_RE": _SECTION_STRICT_RE,
        "SECTION_BARE_RE": _SECTION_BARE_RE,
    }

    for name, pattern in article_regexes.items():
        raw_count = 0
        toc_count = 0
        for m in pattern.finditer(text):
            raw_count += 1
            if _is_toc_entry(text, m.start(), m.end()):
                toc_count += 1
        regex_results[name] = {"raw": raw_count, "toc_rejected": toc_count}
        total_article_raw += raw_count
        total_article_toc += toc_count

    for name, pattern in section_regexes.items():
        raw_count = 0
        toc_count = 0
        for m in pattern.finditer(text):
            raw_count += 1
            if _is_toc_entry(text, m.start(), m.end()):
                toc_count += 1
        regex_results[name] = {"raw": raw_count, "toc_rejected": toc_count}
        total_section_raw += raw_count
        total_section_toc += toc_count

    record["regex_results"] = regex_results
    record["total_article_raw"] = total_article_raw
    record["total_section_raw"] = total_section_raw

    # Check for alternative heading patterns (Part/Chapter/Clause/flat numbered)
    alt_patterns: dict[str, int] = {}
    alt_patterns["PART_matches"] = len(re.findall(
        r"(?:^|\n)\s*(?:PART|Part)\s+([IVX]+|\d+|[A-Za-z]+)\b", text,
    ))
    alt_patterns["CHAPTER_matches"] = len(re.findall(
        r"(?:^|\n)\s*(?:CHAPTER|Chapter)\s+([IVX]+|\d+)\b", text,
    ))
    alt_patterns["CLAUSE_toplevel_matches"] = len(re.findall(
        r"(?:^|\n)\s*(?:CLAUSE|Clause)\s+(\d+)\b", text,
    ))
    alt_patterns["flat_numbered_matches"] = len(re.findall(
        r"(?:^|\n)\s*(\d{1,2})\.\s+([A-Z][A-Za-z][^\n]{0,120})", text,
    ))
    record["alt_patterns"] = alt_patterns

    # Run DocOutline.from_text() and report final section count
    outline = DocOutline.from_text(text, filename=str(html_path))
    record["final_section_count"] = len(outline.sections)
    record["final_article_count"] = len(outline.articles)

    # Classify failure mode
    record["failure_mode"] = _classify_failure(
        word_count=record["word_count"],
        doc_type=doc_type,
        raw_article_matches=total_article_raw,
        raw_section_matches=total_section_raw,
        toc_rejected_articles=total_article_toc,
        toc_rejected_sections=total_section_toc,
        final_section_count=record["final_section_count"],
        text_length=record["text_length"],
        non_ascii_ratio=record["non_ascii_ratio"],
    )

    return record


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose zero-section documents in the corpus",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=Path("corpus"),
        help="Path to corpus HTML directory (default: corpus/)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("corpus_index/corpus.duckdb"),
        help="Path to DuckDB corpus index (default: corpus_index/corpus.duckdb)",
    )
    parser.add_argument(
        "--all-docs",
        action="store_true",
        help="Process ALL docs (not just zero-section), for regression checking",
    )
    parser.add_argument(
        "--spot-check",
        type=int,
        default=0,
        help="When --all-docs, randomly sample N docs that HAVE sections (seed=42)",
    )
    args = parser.parse_args()

    corpus_dir: Path = args.corpus_dir
    db_path: Path = args.db

    if not db_path.exists():
        print(f"Error: DuckDB file not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    if not corpus_dir.is_dir():
        print(f"Error: corpus directory not found: {corpus_dir}", file=sys.stderr)
        sys.exit(1)

    idx = CorpusIndex(db_path)

    # Query zero-section docs
    if args.all_docs and args.spot_check > 0:
        # All zero-section + random sample of non-zero
        zero_rows = idx.query(
            "SELECT doc_id, path, doc_type, word_count FROM documents WHERE section_count = 0"
        )
        nonzero_rows = idx.query(
            "SELECT doc_id, path, doc_type, word_count FROM documents WHERE section_count > 0"
        )
        rng = random.Random(42)
        sampled = rng.sample(nonzero_rows, min(args.spot_check, len(nonzero_rows)))
        rows = list(zero_rows) + sampled
        print(
            f"Processing {len(zero_rows)} zero-section + {len(sampled)} spot-check docs",
            file=sys.stderr,
        )
    elif args.all_docs:
        rows = idx.query(
            "SELECT doc_id, path, doc_type, word_count FROM documents"
        )
        print(f"Processing all {len(rows)} docs", file=sys.stderr)
    else:
        rows = idx.query(
            "SELECT doc_id, path, doc_type, word_count FROM documents WHERE section_count = 0"
        )
        print(f"Found {len(rows)} zero-section documents", file=sys.stderr)

    idx.close()

    # Process each doc
    results: list[dict[str, Any]] = []
    failure_mode_counts: dict[str, int] = {}

    for i, row in enumerate(rows):
        doc_id = str(row[0])
        rel_path = str(row[1])
        doc_type = str(row[2]) if row[2] else ""
        db_word_count = int(row[3]) if row[3] else 0

        html_path = corpus_dir / rel_path
        if not html_path.exists():
            results.append({
                "doc_id": doc_id,
                "failure_mode": "file_not_found",
                "html_path": str(html_path),
            })
            failure_mode_counts["file_not_found"] = (
                failure_mode_counts.get("file_not_found", 0) + 1
            )
            continue

        print(
            f"  [{i + 1}/{len(rows)}] {doc_id}...",
            file=sys.stderr,
            end="\r",
        )

        record = _diagnose_one(doc_id, html_path, doc_type, db_word_count)
        results.append(record)

        mode = record["failure_mode"]
        failure_mode_counts[mode] = failure_mode_counts.get(mode, 0) + 1

    print("", file=sys.stderr)  # Clear progress line

    # Build summary report
    report: dict[str, Any] = {
        "total_docs": len(results),
        "failure_mode_counts": dict(
            sorted(failure_mode_counts.items(), key=lambda kv: -kv[1])
        ),
        "docs": results,
    }

    print(_json_dumps(report))
    print(
        f"Done. {len(results)} docs diagnosed. Failure modes: {failure_mode_counts}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
