#!/usr/bin/env python3
"""Hit rates by template group (or any grouping column).

Usage:
    python3 scripts/coverage_reporter.py --db corpus_index/corpus.duckdb \
      --strategy strategies/indebtedness.json --group-by template_family

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
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


from agent.corpus import CorpusIndex
from agent.strategy import load_strategy, Strategy
from agent.textmatch import heading_matches, keyword_density, section_dna_density, score_in_range


# ---------------------------------------------------------------------------
# Scoring (shared with pattern_tester)
# ---------------------------------------------------------------------------

HEADING_SCORE = 0.80
KEYWORD_MIN = 0.40
KEYWORD_MAX = 0.70
DNA_MIN = 0.25
DNA_MAX = 0.55
HIT_THRESHOLD = 0.3


def score_section(
    heading: str,
    text_lower: str,
    strategy: Strategy,
) -> tuple[float, str]:
    """Score a section against a strategy.

    Returns (score, match_method).
    """
    best_score = 0.0
    method = "none"

    # Heading match
    heading_pat = heading_matches(heading, list(strategy.heading_patterns))
    if heading_pat is not None:
        best_score = HEADING_SCORE
        method = "heading"

    # Keyword density
    kw_density, _ = keyword_density(text_lower, list(strategy.keyword_anchors))
    kw_score = score_in_range(KEYWORD_MIN, KEYWORD_MAX, kw_density)
    if kw_density > 0:
        composite = max(best_score, kw_score)
        if composite > best_score:
            best_score = composite
            method = "keyword"

    # DNA density
    dna_density, _ = section_dna_density(
        text_lower, list(strategy.dna_tier1), list(strategy.dna_tier2)
    )
    dna_score = score_in_range(DNA_MIN, DNA_MAX, dna_density)
    if dna_density > 0:
        composite = max(best_score, dna_score)
        if composite > best_score:
            best_score = composite
            method = "dna"

    # Composite boost: heading + keyword or heading + dna
    if heading_pat is not None and (kw_density > 0 or dna_density > 0):
        combined = HEADING_SCORE + kw_score * 0.3 + dna_score * 0.2
        if combined > best_score:
            best_score = combined
            method = "composite"

    return best_score, method


def best_doc_score(
    corpus: CorpusIndex,
    doc_id: str,
    strategy: Strategy,
) -> float:
    """Return the best section score for a document."""
    sections = corpus.search_sections(doc_id=doc_id, limit=9999)
    best = 0.0
    for sec in sections:
        text = corpus.get_section_text(doc_id, sec.section_number)
        text_lower = text.lower() if text else ""
        score, _ = score_section(sec.heading, text_lower, strategy)
        if score > best:
            best = score
    return best


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    strategy = load_strategy(Path(args.strategy))
    group_by = args.group_by
    print(f"Loaded strategy: {strategy.concept_id} v{strategy.version}", file=sys.stderr)
    print(f"Grouping by: {group_by}", file=sys.stderr)

    with CorpusIndex(Path(args.db)) as corpus:
        # Determine doc list
        if args.sample:
            doc_ids = corpus.sample_docs(args.sample, seed=args.seed)
            print(f"Sampled {len(doc_ids)} docs (seed={args.seed})", file=sys.stderr)
        else:
            doc_ids = corpus.doc_ids()
            print(f"Testing all {len(doc_ids)} docs", file=sys.stderr)

        # Group docs and score
        group_hits: defaultdict[str, int] = defaultdict(int)
        group_totals: defaultdict[str, int] = defaultdict(int)
        total_hits = 0

        for i, doc_id in enumerate(doc_ids):
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(doc_ids)}", file=sys.stderr)

            # Get group value
            doc_rec = corpus.get_doc(doc_id)
            if doc_rec is None:
                group_val = "unknown"
            else:
                group_val = getattr(doc_rec, group_by, None)
                if group_val is None:
                    group_val = "unknown"
                group_val = str(group_val)
                if not group_val:
                    group_val = "unknown"

            group_totals[group_val] += 1

            # Score document
            score = best_doc_score(corpus, doc_id, strategy)
            if score > HIT_THRESHOLD:
                group_hits[group_val] += 1
                total_hits += 1

        # Build output
        total = len(doc_ids)
        overall_hit_rate = round(total_hits / total, 4) if total > 0 else 0.0

        by_group: dict[str, dict[str, Any]] = {}
        for gv in sorted(group_totals.keys()):
            n = group_totals[gv]
            h = group_hits.get(gv, 0)
            by_group[gv] = {
                "hit_rate": round(h / n, 4) if n > 0 else 0.0,
                "n": n,
                "hits": h,
            }

        output: dict[str, Any] = {
            "strategy": strategy.concept_id,
            "overall": {
                "hit_rate": overall_hit_rate,
                "n": total,
                "hits": total_hits,
            },
            "by_group": by_group,
        }

        dump_json(output)

    print(
        f"Done: {total_hits}/{total} hits ({overall_hit_rate:.1%})",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hit rates by template group (or any grouping column)."
    )
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument("--strategy", required=True, help="Path to strategy JSON file")
    parser.add_argument(
        "--group-by",
        default="template_family",
        help="Column to group by (default: template_family)",
    )
    parser.add_argument("--sample", type=int, default=None, help="Test on N random docs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
