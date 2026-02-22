#!/usr/bin/env python3
"""Discover heading variants for a concept across the corpus.

Usage:
    python3 scripts/heading_discoverer.py --db corpus_index/corpus.duckdb \
      --seed-headings "Indebtedness,Limitation on Indebtedness" \
      --article-range 6-8 --sample 500

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
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


def parse_article_range(range_str: str) -> tuple[int, int]:
    """Parse an article range string like '6-8' into (6, 8)."""
    parts = range_str.split("-")
    if len(parts) == 1:
        v = int(parts[0])
        return v, v
    elif len(parts) == 2:
        return int(parts[0]), int(parts[1])
    else:
        raise ValueError(f"Invalid article range: {range_str!r} (expected e.g. '6-8')")


def run(args: argparse.Namespace) -> None:
    seed_headings = [h.strip() for h in args.seed_headings.split(",") if h.strip()]
    seed_headings_lower = [h.lower() for h in seed_headings]
    print(f"Seed headings: {seed_headings}", file=sys.stderr)

    article_lo: int | None = None
    article_hi: int | None = None
    if args.article_range:
        article_lo, article_hi = parse_article_range(args.article_range)
        print(f"Article range: {article_lo}-{article_hi}", file=sys.stderr)

    with CorpusIndex(Path(args.db)) as corpus:
        # Determine doc list
        if args.sample:
            doc_ids = corpus.sample_docs(args.sample, seed=args.seed)
            print(f"Sampled {len(doc_ids)} docs (seed={args.seed})", file=sys.stderr)
        else:
            doc_ids = corpus.doc_ids()
            print(f"Searching all {len(doc_ids)} docs", file=sys.stderr)

        # heading -> {frequency, article_nums, example_doc_ids}
        heading_freq: Counter[str] = Counter()
        heading_articles: defaultdict[str, Counter[int]] = defaultdict(Counter)
        heading_examples: defaultdict[str, list[str]] = defaultdict(list)

        for i, doc_id in enumerate(doc_ids):
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(doc_ids)}", file=sys.stderr)

            sections = corpus.search_sections(doc_id=doc_id, limit=9999)

            # Optionally filter by article range
            if article_lo is not None and article_hi is not None:
                sections = [
                    s for s in sections
                    if article_lo <= s.article_num <= article_hi
                ]

            if not sections:
                continue

            # Check if any section heading contains a seed pattern
            matched_articles: set[int] = set()
            for sec in sections:
                heading_lower = sec.heading.lower()
                for seed in seed_headings_lower:
                    if seed in heading_lower:
                        matched_articles.add(sec.article_num)
                        break

            if not matched_articles:
                continue

            # Collect ALL distinct headings from matched articles in this doc
            seen_headings_in_doc: set[str] = set()
            for sec in sections:
                if sec.article_num in matched_articles:
                    h = sec.heading.strip()
                    if h and h not in seen_headings_in_doc:
                        seen_headings_in_doc.add(h)
                        heading_freq[h] += 1
                        heading_articles[h][sec.article_num] += 1
                        if len(heading_examples[h]) < 3:
                            heading_examples[h].append(doc_id)

        # Filter by min frequency and sort
        min_freq = args.min_frequency
        results: list[dict[str, Any]] = []
        for heading, freq in heading_freq.most_common():
            if freq < min_freq:
                continue
            # Most common article for this heading
            article_counter = heading_articles[heading]
            most_common_article = article_counter.most_common(1)[0][0] if article_counter else 0
            results.append({
                "heading": heading,
                "frequency": freq,
                "article": most_common_article,
                "example_doc_ids": heading_examples[heading],
            })

        dump_json(results)

    print(
        f"Done: found {len(results)} distinct headings "
        f"(min_frequency={min_freq})",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover heading variants for a concept across the corpus."
    )
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument(
        "--seed-headings",
        required=True,
        help="Comma-separated seed heading patterns",
    )
    parser.add_argument(
        "--article-range",
        default=None,
        help="Article number range to search (e.g., '6-8')",
    )
    parser.add_argument("--sample", type=int, default=None, help="Search in N random docs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=2,
        help="Minimum occurrence count to report (default: 2)",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
