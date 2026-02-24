#!/usr/bin/env python3
"""Map structural positions for a concept across the corpus.

Usage:
    python3 scripts/structural_mapper.py --db corpus_index/corpus.duckdb \
      --strategy workspaces/indebtedness/strategies/current.json --sample 500

    python3 scripts/structural_mapper.py --db corpus_index/corpus.duckdb \
      --concept indebtedness \
      --heading-patterns "Indebtedness,Limitation on Indebtedness" --sample 500

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
from agent.structural_fingerprint import (
    build_section_fingerprint,
    feature_discrimination_score,
    summarize_fingerprints,
)
from agent.strategy import Strategy, load_strategy
from agent.textmatch import (
    heading_matches,
    keyword_density,
    score_in_range,
    section_dna_density,
)

HEADING_SCORE = 0.80
KEYWORD_MIN = 0.40
KEYWORD_MAX = 0.70
DNA_MIN = 0.25
DNA_MAX = 0.55
DEFAULT_MATCH_THRESHOLD = 0.30

_ROMAN_PAIRS = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def parse_csv(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def uniq(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def int_to_roman(value: int) -> str:
    if value <= 0:
        return "UNKNOWN"
    n = value
    out: list[str] = []
    for arabic, roman in _ROMAN_PAIRS:
        while n >= arabic:
            out.append(roman)
            n -= arabic
        if n == 0:
            break
    return "".join(out) if out else "UNKNOWN"


def section_suffix(section_number: str) -> str | None:
    if "." not in section_number:
        return None
    suffix = section_number.split(".", 1)[1].strip()
    if not suffix:
        return None
    return f".{suffix}"


def sorted_counter(counter: Counter[str | int]) -> dict[str, int]:
    items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return {str(k): int(v) for k, v in items}


def score_section(
    heading: str,
    text_lower: str,
    heading_patterns: list[str],
    keyword_anchors: list[str],
    dna_tier1: list[str],
    dna_tier2: list[str],
) -> tuple[float, str]:
    """Return (score, method) for a section."""
    best_score = 0.0
    method = "none"

    heading_pat = heading_matches(heading, heading_patterns)
    if heading_pat is not None:
        best_score = HEADING_SCORE
        method = "heading"

    kw_density, _ = keyword_density(text_lower, keyword_anchors)
    kw_score = score_in_range(KEYWORD_MIN, KEYWORD_MAX, kw_density)
    if kw_density > 0 and kw_score > best_score:
        best_score = kw_score
        method = "keyword"

    dna_density, _ = section_dna_density(text_lower, dna_tier1, dna_tier2)
    dna_score = score_in_range(DNA_MIN, DNA_MAX, dna_density)
    if dna_density > 0 and dna_score > best_score:
        best_score = dna_score
        method = "dna"

    if heading_pat is not None and (kw_density > 0 or dna_density > 0):
        combined = HEADING_SCORE + kw_score * 0.3 + dna_score * 0.2
        if combined > best_score:
            best_score = combined
            method = "composite"

    return best_score, method


def resolve_vocab(
    args: argparse.Namespace,
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    strategy: Strategy | None = None
    if args.strategy:
        strategy = load_strategy(Path(args.strategy))

    concept = args.concept
    if not concept and strategy is not None:
        concept = strategy.concept_id
    if not concept:
        concept = "custom"

    heading_patterns = parse_csv(args.heading_patterns)
    keyword_anchors = parse_csv(args.keyword_anchors)
    dna_tier1 = parse_csv(args.dna_tier1)
    dna_tier2 = parse_csv(args.dna_tier2)

    if strategy is not None:
        heading_patterns = list(strategy.heading_patterns) + heading_patterns
        keyword_anchors = list(strategy.keyword_anchors) + keyword_anchors
        dna_tier1 = list(strategy.dna_tier1) + dna_tier1
        dna_tier2 = list(strategy.dna_tier2) + dna_tier2

    heading_patterns = uniq(heading_patterns)
    keyword_anchors = uniq(keyword_anchors)
    dna_tier1 = uniq(dna_tier1)
    dna_tier2 = uniq(dna_tier2)

    return concept, heading_patterns, keyword_anchors, dna_tier1, dna_tier2


def run(args: argparse.Namespace) -> None:
    concept, heading_patterns, keyword_anchors, dna_tier1, dna_tier2 = resolve_vocab(args)
    if not heading_patterns and not keyword_anchors and not dna_tier1 and not dna_tier2:
        print(
            "Error: provide --strategy and/or heading/keyword/DNA patterns.",
            file=sys.stderr,
        )
        sys.exit(1)

    cohort_only = not args.include_all
    print(f"Concept: {concept}", file=sys.stderr)
    print(
        "Signals: "
        f"headings={len(heading_patterns)}, "
        f"keywords={len(keyword_anchors)}, "
        f"dna1={len(dna_tier1)}, dna2={len(dna_tier2)}",
        file=sys.stderr,
    )

    with CorpusIndex(Path(args.db)) as corpus:
        if args.doc_ids:
            doc_ids = [
                line.strip()
                for line in Path(args.doc_ids).read_text().splitlines()
                if line.strip()
            ]
            print(f"Loaded {len(doc_ids)} doc IDs from {args.doc_ids}", file=sys.stderr)
        elif args.sample:
            doc_ids = corpus.sample_docs(
                args.sample,
                seed=args.seed,
                cohort_only=cohort_only,
            )
            print(f"Sampled {len(doc_ids)} docs (seed={args.seed})", file=sys.stderr)
        else:
            doc_ids = corpus.doc_ids(cohort_only=cohort_only)
            print(f"Scanning all {len(doc_ids)} docs", file=sys.stderr)

        article_counts: Counter[int] = Counter()
        section_counts: Counter[str] = Counter()
        suffix_counts: Counter[str] = Counter()
        heading_counts: Counter[str] = Counter()
        match_method_counts: Counter[str] = Counter()
        fingerprints = []
        fingerprints_by_template: dict[str, list] = {}

        matched_docs = 0
        examples: list[dict[str, Any]] = []

        for i, doc_id in enumerate(doc_ids):
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(doc_ids)}", file=sys.stderr)

            sections = corpus.search_sections(
                doc_id=doc_id,
                cohort_only=cohort_only,
                limit=9999,
            )
            if not sections:
                continue

            best_score = 0.0
            best_method = "none"
            best_section = ""
            best_article = 0
            best_heading = ""
            best_text = ""

            for sec in sections:
                text = corpus.get_section_text(doc_id, sec.section_number)
                text_lower = text.lower() if text else ""
                score, method = score_section(
                    sec.heading,
                    text_lower,
                    heading_patterns,
                    keyword_anchors,
                    dna_tier1,
                    dna_tier2,
                )
                if score > best_score:
                    best_score = score
                    best_method = method
                    best_section = sec.section_number
                    best_article = sec.article_num
                    best_heading = sec.heading
                    best_text = text

            if best_score < args.match_threshold:
                continue

            matched_docs += 1
            article_counts[best_article] += 1
            section_counts[best_section] += 1
            if best_heading:
                heading_counts[best_heading] += 1
            match_method_counts[best_method] += 1

            suffix = section_suffix(best_section)
            if suffix:
                suffix_counts[suffix] += 1

            examples.append({
                "doc_id": doc_id,
                "section_number": best_section,
                "article_num": best_article,
                "article": int_to_roman(best_article),
                "heading": best_heading,
                "score": round(best_score, 4),
                "match_method": best_method,
            })
            doc_rec = corpus.get_doc(doc_id)
            template_family = doc_rec.template_family if doc_rec else "unknown"
            fp = build_section_fingerprint(
                template_family=template_family or "unknown",
                article_num=best_article,
                section_number=best_section,
                heading=best_heading,
                text=best_text,
            )
            fingerprints.append(fp)
            fingerprints_by_template.setdefault(template_family or "unknown", []).append(fp)

        examples.sort(key=lambda row: row["score"], reverse=True)
        if args.max_examples >= 0:
            examples = examples[: args.max_examples]

        article_distribution = {
            int_to_roman(int(k)): int(v)
            for k, v in sorted(article_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        }
        section_distribution = sorted_counter(section_counts)
        heading_distribution = sorted_counter(heading_counts)
        method_distribution = sorted_counter(match_method_counts)
        section_suffix_distribution = sorted_counter(suffix_counts)

        total_docs = len(doc_ids)
        match_rate = round(matched_docs / total_docs, 4) if total_docs else 0.0

        top_article = article_counts.most_common(1)[0][0] if article_counts else 0
        top_section = section_counts.most_common(1)[0][0] if section_counts else ""
        top_suffix = suffix_counts.most_common(1)[0][0] if suffix_counts else ""

        output: dict[str, Any] = {
            "concept": concept,
            "total_docs": total_docs,
            "matched_docs": matched_docs,
            "match_rate": match_rate,
            "article_distribution": article_distribution,
            "section_distribution": section_distribution,
            "section_suffix_distribution": section_suffix_distribution,
            "heading_distribution": heading_distribution,
            "match_method_distribution": method_distribution,
            "typical_position": {
                "article": int_to_roman(top_article) if top_article else "UNKNOWN",
                "article_num": int(top_article) if top_article else 0,
                "section": top_section,
                "section_suffix": top_suffix,
            },
            "inputs": {
                "strategy": args.strategy or "",
                "heading_patterns": heading_patterns,
                "keyword_anchors": keyword_anchors,
                "dna_tier1": dna_tier1,
                "dna_tier2": dna_tier2,
                "match_threshold": args.match_threshold,
                "cohort_only": cohort_only,
            },
            "examples": examples,
            "structural_fingerprint_summary": summarize_fingerprints(fingerprints),
            "structural_discrimination_by_template": feature_discrimination_score(
                fingerprints_by_template
            ),
        }

        dump_json(output)

    print(
        f"Done: matched {matched_docs}/{total_docs} docs ({match_rate:.1%})",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Map structural positions for a concept across the corpus."
    )
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument("--concept", default="", help="Concept name/id for output metadata.")
    parser.add_argument(
        "--strategy",
        default="",
        help="Optional strategy JSON to source headings/keywords/DNA.",
    )
    parser.add_argument(
        "--heading-patterns",
        default="",
        help="Comma-separated heading patterns to merge with strategy headings.",
    )
    parser.add_argument(
        "--keyword-anchors",
        default="",
        help="Comma-separated keyword anchors to merge with strategy keywords.",
    )
    parser.add_argument(
        "--dna-tier1",
        default="",
        help="Comma-separated tier-1 DNA phrases to merge with strategy DNA.",
    )
    parser.add_argument(
        "--dna-tier2",
        default="",
        help="Comma-separated tier-2 DNA phrases to merge with strategy DNA.",
    )
    parser.add_argument(
        "--doc-ids",
        default="",
        help="Optional file with newline-delimited doc IDs.",
    )
    parser.add_argument("--sample", type=int, default=None, help="Run on N random docs.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling.")
    parser.add_argument(
        "--match-threshold",
        type=float,
        default=DEFAULT_MATCH_THRESHOLD,
        help=(
            "Document considered matched when best section score >= threshold "
            f"(default: {DEFAULT_MATCH_THRESHOLD})."
        ),
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=20,
        help="Maximum number of top-scoring example matches to emit.",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
