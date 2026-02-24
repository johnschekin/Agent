#!/usr/bin/env python3
"""Discover heading variants for a concept across the corpus.

Usage:
    python3 scripts/heading_discoverer.py --db corpus_index/corpus.duckdb \
      --seed-headings "Indebtedness,Limitation on Indebtedness" \
      --article-range 6-8 --sample 500

    # Optional canonical concept tagging from bootstrap registry:
    python3 scripts/heading_discoverer.py --db corpus_index/corpus.duckdb \
      --seed-headings "Indebtedness,Limitation on Indebtedness" \
      --with-canonical-summary

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import datetime as dt
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

DEFAULT_BOOTSTRAP_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "bootstrap" / "bootstrap_all.json"
)


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


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def parse_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _strategy_entries(raw: Any) -> list[tuple[str, dict[str, Any]]]:
    entries: list[tuple[str, dict[str, Any]]] = []
    if isinstance(raw, dict):
        if "strategies" in raw and isinstance(raw["strategies"], list):
            for rec in raw["strategies"]:
                if not isinstance(rec, dict):
                    continue
                concept_id = str(rec.get("concept_id") or rec.get("id") or "").strip()
                if concept_id:
                    entries.append((concept_id, rec))
            return entries
        for key, rec in raw.items():
            if not isinstance(rec, dict):
                continue
            concept_id = str(rec.get("id") or rec.get("concept_id") or key).strip()
            if concept_id:
                entries.append((concept_id, rec))
    return entries


def load_canonical_concepts(bootstrap_path: Path) -> dict[str, tuple[str, ...]]:
    """Load CANONICAL_CONCEPTS from bootstrap strategy data.

    Output shape:
        concept_id -> tuple(alias strings)
    """
    raw = json.loads(bootstrap_path.read_text())
    concepts: dict[str, tuple[str, ...]] = {}

    for concept_id, rec in _strategy_entries(raw):
        search_strategy = rec.get("search_strategy")
        if not isinstance(search_strategy, dict):
            search_strategy = rec

        aliases: list[str] = []
        name = str(rec.get("name") or rec.get("concept_name") or "").strip()
        if name:
            aliases.append(name)

        family_id = str(rec.get("family_id") or rec.get("family") or "").strip()
        if family_id:
            aliases.append(family_id.split(".")[-1].replace("_", " "))

        aliases.append(concept_id.split(".")[-1].replace("_", " "))

        heading_patterns = search_strategy.get("heading_patterns", [])
        if isinstance(heading_patterns, list):
            for heading in heading_patterns:
                if isinstance(heading, str) and heading.strip():
                    aliases.append(heading.strip())

        seen: set[str] = set()
        deduped: list[str] = []
        for alias in aliases:
            norm = normalize_text(alias)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            deduped.append(alias)

        if deduped:
            concepts[concept_id] = tuple(deduped)

    return concepts


def build_alias_index(canonical_concepts: dict[str, tuple[str, ...]]) -> dict[str, set[str]]:
    alias_index: dict[str, set[str]] = defaultdict(set)
    for concept_id, aliases in canonical_concepts.items():
        for alias in aliases:
            norm = normalize_text(alias)
            if norm:
                alias_index[norm].add(concept_id)
    return alias_index


def canonical_matches_for_heading(
    heading: str,
    alias_index: dict[str, set[str]],
    *,
    max_candidates: int,
) -> list[str]:
    norm_heading = normalize_text(heading)
    if not norm_heading:
        return []

    matches: set[str] = set(alias_index.get(norm_heading, set()))
    for alias_norm, concept_ids in alias_index.items():
        if alias_norm == norm_heading:
            continue
        # Very short aliases ("debt", "lien") are only reliable as exact matches.
        if len(alias_norm) <= 5:
            continue
        if alias_norm in norm_heading or norm_heading in alias_norm:
            matches.update(concept_ids)

    out = sorted(matches)
    return out[:max_candidates]


def run(args: argparse.Namespace) -> None:
    seed_headings = parse_csv(args.seed_headings)
    seed_headings_lower = [h.lower() for h in seed_headings]
    cohort_only = not args.include_all
    print(f"Seed headings: {seed_headings}", file=sys.stderr)

    article_lo: int | None = None
    article_hi: int | None = None
    if args.article_range:
        article_lo, article_hi = parse_article_range(args.article_range)
        print(f"Article range: {article_lo}-{article_hi}", file=sys.stderr)

    canonical_concepts: dict[str, tuple[str, ...]] = {}
    canonical_alias_index: dict[str, set[str]] = {}
    if not args.no_canonical:
        canonical_bootstrap = Path(args.canonical_bootstrap)
        if canonical_bootstrap.exists():
            canonical_concepts = load_canonical_concepts(canonical_bootstrap)
            canonical_alias_index = build_alias_index(canonical_concepts)
            alias_count = sum(len(v) for v in canonical_concepts.values())
            print(
                "Loaded CANONICAL_CONCEPTS from bootstrap: "
                f"{len(canonical_concepts)} concepts / {alias_count} aliases",
                file=sys.stderr,
            )
        else:
            print(
                f"Warning: canonical bootstrap file not found at {canonical_bootstrap}; "
                "continuing without canonical mapping",
                file=sys.stderr,
            )

    with CorpusIndex(Path(args.db)) as corpus:
        # Determine doc list
        if args.sample:
            doc_ids = corpus.sample_docs(
                args.sample,
                seed=args.seed,
                cohort_only=cohort_only,
            )
            print(f"Sampled {len(doc_ids)} docs (seed={args.seed})", file=sys.stderr)
        else:
            doc_ids = corpus.doc_ids(cohort_only=cohort_only)
            print(f"Searching all {len(doc_ids)} docs", file=sys.stderr)

        # heading -> {frequency, article_nums, example_doc_ids}
        heading_freq: Counter[str] = Counter()
        heading_articles: defaultdict[str, Counter[int]] = defaultdict(Counter)
        heading_examples: defaultdict[str, list[str]] = defaultdict(list)

        for i, doc_id in enumerate(doc_ids):
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(doc_ids)}", file=sys.stderr)

            sections = corpus.search_sections(
                doc_id=doc_id,
                cohort_only=cohort_only,
                limit=9999,
            )

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
        canonical_summary_counts: Counter[str] = Counter()
        canonical_summary_headings: defaultdict[str, set[str]] = defaultdict(set)
        mapped_heading_count = 0

        for heading, freq in heading_freq.most_common():
            if freq < min_freq:
                continue
            # Most common article for this heading
            article_counter = heading_articles[heading]
            most_common_article = article_counter.most_common(1)[0][0] if article_counter else 0
            canonical_candidates: list[str] = []
            canonical_primary: str | None = None
            if canonical_alias_index:
                canonical_candidates = canonical_matches_for_heading(
                    heading,
                    canonical_alias_index,
                    max_candidates=args.max_canonical_candidates,
                )
                if canonical_candidates:
                    mapped_heading_count += 1
                    if len(canonical_candidates) == 1:
                        canonical_primary = canonical_candidates[0]
                    for concept_id in canonical_candidates:
                        canonical_summary_counts[concept_id] += freq
                        canonical_summary_headings[concept_id].add(heading)

            results.append({
                "heading": heading,
                "frequency": freq,
                "article": most_common_article,
                "example_doc_ids": heading_examples[heading],
                "canonical_concept": canonical_primary,
                "canonical_candidates": canonical_candidates,
            })

        if args.with_canonical_summary:
            registry_candidates: list[dict[str, Any]] = []
            if args.with_registry_candidates:
                for row in results:
                    if row["frequency"] < args.registry_candidate_min_frequency:
                        continue
                    if row.get("canonical_candidates"):
                        continue
                    heading = str(row.get("heading", ""))
                    slug = normalize_text(heading).replace(" ", "_")
                    registry_candidates.append(
                        {
                            "heading": heading,
                            "frequency": int(row["frequency"]),
                            "suggested_concept_id": slug,
                            "suggested_aliases": [heading],
                        }
                    )
                registry_candidates.sort(
                    key=lambda item: (-int(item["frequency"]), str(item["heading"]))
                )
                if args.registry_out:
                    payload = {
                        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
                        "base_registry_concept_count": len(canonical_concepts),
                        "candidate_count": len(registry_candidates),
                        "candidates": registry_candidates,
                    }
                    out_path = Path(args.registry_out)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(json.dumps(payload, indent=2))

            summary = [
                {
                    "concept_id": concept_id,
                    "frequency": count,
                    "distinct_headings": len(canonical_summary_headings[concept_id]),
                }
                for concept_id, count in canonical_summary_counts.most_common()
                if count >= args.canonical_min_frequency
            ]
            dump_json({
                "results": results,
                "canonical_summary": summary,
                "canonical_registry_stats": {
                    "concept_count": len(canonical_concepts),
                    "alias_count": len(canonical_alias_index),
                    "mapped_heading_count": mapped_heading_count,
                },
                "registry_expansion_candidates": registry_candidates
                if args.with_registry_candidates
                else [],
            })
        else:
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
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=2,
        help="Minimum occurrence count to report (default: 2)",
    )
    parser.add_argument(
        "--canonical-bootstrap",
        default=str(DEFAULT_BOOTSTRAP_PATH),
        help="Path to bootstrap_all.json used to build CANONICAL_CONCEPTS.",
    )
    parser.add_argument(
        "--no-canonical",
        action="store_true",
        help="Disable canonical concept mapping.",
    )
    parser.add_argument(
        "--max-canonical-candidates",
        type=int,
        default=5,
        help="Maximum canonical concept candidates to emit per heading.",
    )
    parser.add_argument(
        "--with-canonical-summary",
        action="store_true",
        help="Emit top-level canonical summary and registry stats.",
    )
    parser.add_argument(
        "--canonical-min-frequency",
        type=int,
        default=1,
        help="Minimum aggregated frequency for canonical summary entries.",
    )
    parser.add_argument(
        "--with-registry-candidates",
        action="store_true",
        help="Emit candidate headings for canonical registry expansion.",
    )
    parser.add_argument(
        "--registry-candidate-min-frequency",
        type=int,
        default=5,
        help="Minimum heading frequency to propose registry expansion candidate.",
    )
    parser.add_argument(
        "--registry-out",
        default=None,
        help="Optional path to write registry expansion candidate JSON.",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
