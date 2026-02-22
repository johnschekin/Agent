#!/usr/bin/env python3
"""Test a strategy against documents with smart failure summarization.

Usage:
    python3 scripts/pattern_tester.py --db corpus_index/corpus.duckdb \
      --strategy strategies/indebtedness.json --sample 500 --verbose

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import json
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


from agent.corpus import CorpusIndex
from agent.strategy import load_strategy, Strategy
from agent.textmatch import heading_matches, keyword_density, section_dna_density, score_in_range


# ---------------------------------------------------------------------------
# Scoring
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

    Returns (score, match_method) where match_method is 'heading',
    'keyword', 'dna', or 'composite'.
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


# ---------------------------------------------------------------------------
# Log-odds discriminator analysis
# ---------------------------------------------------------------------------

def compute_log_odds_discriminators(
    miss_headings: Counter[str],
    hit_headings: Counter[str],
    total_misses: int,
    total_hits: int,
    *,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Find headings that discriminate misses from hits via simple rate ratio."""
    all_headings = set(miss_headings.keys()) | set(hit_headings.keys())
    results: list[dict[str, Any]] = []

    for h in all_headings:
        miss_count = miss_headings.get(h, 0)
        hit_count = hit_headings.get(h, 0)
        miss_rate = miss_count / total_misses if total_misses > 0 else 0.0
        hit_rate = hit_count / total_hits if total_hits > 0 else 0.0

        # Only include if it discriminates toward misses
        if miss_rate > hit_rate and miss_count >= 2:
            results.append({
                "phrase": h,
                "miss_rate": round(miss_rate, 4),
                "hit_rate": round(hit_rate, 4),
            })

    results.sort(key=lambda x: x["miss_rate"] - x["hit_rate"], reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    strategy = load_strategy(Path(args.strategy))
    print(f"Loaded strategy: {strategy.concept_id} v{strategy.version}", file=sys.stderr)

    with CorpusIndex(Path(args.db)) as corpus:
        # Determine doc list
        if args.doc_ids:
            doc_id_path = Path(args.doc_ids)
            doc_ids = [
                line.strip()
                for line in doc_id_path.read_text().splitlines()
                if line.strip()
            ]
            print(f"Loaded {len(doc_ids)} doc IDs from {args.doc_ids}", file=sys.stderr)
        elif args.sample:
            doc_ids = corpus.sample_docs(args.sample, seed=args.seed)
            print(f"Sampled {len(doc_ids)} docs (seed={args.seed})", file=sys.stderr)
        else:
            doc_ids = corpus.doc_ids()
            print(f"Testing all {len(doc_ids)} docs", file=sys.stderr)

        # Per-doc scoring
        hits: list[dict[str, Any]] = []
        misses: list[dict[str, Any]] = []
        all_scores: list[float] = []
        heading_hit_count = 0
        section_positions: list[float] = []

        # For miss analysis
        miss_headings: Counter[str] = Counter()
        hit_headings: Counter[str] = Counter()
        miss_templates: Counter[str] = Counter()
        miss_articles: Counter[str] = Counter()
        nearest_misses: list[dict[str, Any]] = []

        for i, doc_id in enumerate(doc_ids):
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(doc_ids)}", file=sys.stderr)

            sections = corpus.search_sections(doc_id=doc_id, limit=9999)
            if not sections:
                # No sections found -- count as miss
                doc_rec = corpus.get_doc(doc_id)
                template = doc_rec.template_family if doc_rec else "unknown"
                misses.append({"doc_id": doc_id, "best_score": 0.0})
                miss_templates[template] += 1
                continue

            best_score = 0.0
            best_section = ""
            best_heading = ""
            best_method = "none"
            best_position = 0

            for idx, sec in enumerate(sections):
                text = corpus.get_section_text(doc_id, sec.section_number)
                text_lower = text.lower() if text else ""
                score, method = score_section(sec.heading, text_lower, strategy)
                if score > best_score:
                    best_score = score
                    best_section = sec.section_number
                    best_heading = sec.heading
                    best_method = method
                    best_position = idx

            doc_rec = corpus.get_doc(doc_id)
            template = doc_rec.template_family if doc_rec else "unknown"

            if best_score > HIT_THRESHOLD:
                # Hit
                all_scores.append(best_score)
                if best_method == "heading" or best_method == "composite":
                    heading_hit_count += 1
                section_positions.append(best_position)

                hit_info: dict[str, Any] = {
                    "doc_id": doc_id,
                    "section": best_section,
                    "heading": best_heading,
                    "score": round(best_score, 4),
                    "match_method": best_method,
                }
                hits.append(hit_info)

                # Collect hit headings for log-odds
                for sec in sections:
                    hit_headings[sec.heading] += 1
            else:
                # Miss
                misses.append({
                    "doc_id": doc_id,
                    "best_score": round(best_score, 4),
                    "best_section": best_section,
                    "best_heading": best_heading,
                })
                miss_templates[template] += 1

                # Collect miss headings for log-odds
                for sec in sections:
                    miss_headings[sec.heading] += 1

                # Structural deviation: which article had the best score
                if best_section:
                    # Extract article from section_number (e.g. "7.01" -> "article_7")
                    article_part = best_section.split(".")[0] if "." in best_section else best_section
                    try:
                        article_key = f"article_{int(article_part)}"
                    except ValueError:
                        article_key = "no_article"
                else:
                    article_key = "no_article"
                miss_articles[article_key] += 1

                # Track nearest misses
                nearest_misses.append({
                    "doc_id": doc_id,
                    "best_score": round(best_score, 4),
                    "best_section": best_section,
                    "best_heading": best_heading,
                })

        # Compute summary statistics
        total = len(doc_ids)
        n_hits = len(hits)
        n_misses = len(misses)
        hit_rate = round(n_hits / total, 4) if total > 0 else 0.0

        # Hit summary
        avg_score = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0
        heading_hr = round(heading_hit_count / n_hits, 4) if n_hits > 0 else 0.0
        avg_pos = round(sum(section_positions) / len(section_positions), 2) if section_positions else 0.0

        # Confidence distribution
        conf_high = sum(1 for s in all_scores if s >= 0.7)
        conf_medium = sum(1 for s in all_scores if 0.4 <= s < 0.7)
        conf_low = sum(1 for s in all_scores if s < 0.4)

        # Miss analysis: top headings
        top_miss_headings = [
            {"heading": h, "count": c}
            for h, c in miss_headings.most_common(20)
        ]

        # Log-odds discriminators
        log_odds = compute_log_odds_discriminators(
            miss_headings, hit_headings, n_misses, n_hits
        )

        # Structural deviation
        structural_dev = dict(miss_articles.most_common(20))

        # Nearest misses (top 10)
        nearest_misses.sort(key=lambda x: x["best_score"], reverse=True)
        nearest_misses = nearest_misses[:10]

        # Template breakdown
        by_template = dict(miss_templates.most_common(20))

        # Build output
        output: dict[str, Any] = {
            "strategy": strategy.concept_id,
            "strategy_version": strategy.version,
            "total_docs": total,
            "hits": n_hits,
            "misses": n_misses,
            "hit_rate": hit_rate,
            "hit_summary": {
                "avg_score": avg_score,
                "heading_hit_rate": heading_hr,
                "avg_section_position": avg_pos,
                "confidence_distribution": {
                    "high": conf_high,
                    "medium": conf_medium,
                    "low": conf_low,
                },
            },
            "miss_summary": {
                "by_template": by_template,
                "top_headings_in_misses": top_miss_headings,
                "log_odds_discriminators": log_odds,
                "structural_deviation": structural_dev,
                "nearest_misses": nearest_misses,
            },
        }

        if args.verbose:
            output["matches"] = hits

        dump_json(output)

    print(
        f"Done: {n_hits}/{total} hits ({hit_rate:.1%}), "
        f"{n_misses} misses",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test a strategy against corpus documents with smart failure summarization."
    )
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument("--strategy", required=True, help="Path to strategy JSON file")
    parser.add_argument("--doc-ids", default=None, help="File with doc IDs to test (one per line)")
    parser.add_argument("--sample", type=int, default=None, help="Test on N random docs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument("--verbose", "-v", action="store_true", help="Include detailed match info")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
