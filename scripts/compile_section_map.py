#!/usr/bin/env python3
"""Compile per-concept section location map with HHI stability scoring.

Queries the DuckDB corpus index to build a prevalence matrix showing which
sections each concept appears in, how concentrated that distribution is
(HHI stability), and what the recommended search strategy should be.

Usage:
    python3 scripts/compile_section_map.py --db corpus_index/corpus.duckdb \
      --strategies workspaces/*/strategies/ --output plans/section_map.json

    # Dry run — show summary without writing:
    python3 scripts/compile_section_map.py --db corpus_index/corpus.duckdb \
      --strategies workspaces/*/strategies/ --dry-run

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import glob
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


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# HHI stability computation
# ---------------------------------------------------------------------------


def compute_hhi(section_counts: Counter[str]) -> float:
    """Compute normalized Herfindahl-Hirschman Index for section distribution.

    Returns:
        Float [0.0, 1.0] where:
        - 1.0 = perfect concentration (all hits in one section)
        - 0.0 = maximum dispersion (uniform across all sections)
        - 0.5 = returned when insufficient data (<2 distinct sections)
    """
    total = sum(section_counts.values())
    n = len(section_counts)
    if total == 0 or n == 0:
        return 0.5
    if n == 1:
        return 1.0

    raw_hhi = sum((c / total) ** 2 for c in section_counts.values())
    min_hhi = 1.0 / n
    if min_hhi >= 1.0:
        return 1.0
    normalized = (raw_hhi - min_hhi) / (1.0 - min_hhi)
    return max(0.0, min(1.0, normalized))


def location_strategy(stability: float) -> str:
    """Map HHI stability score to a recommended search strategy."""
    if stability >= 0.7:
        return "adjacent_sections"
    if stability >= 0.3:
        return "same_article"
    return "full_article_scan"


# ---------------------------------------------------------------------------
# Strategy evidence loading
# ---------------------------------------------------------------------------


def load_strategy_evidence(
    strategy_dirs: list[Path],
) -> dict[str, dict[str, Any]]:
    """Load latest strategy files and extract section location evidence.

    Returns: {concept_id: {sections: Counter, articles: Counter,
              headings: list, n_strategies: int, best_score: float}}
    """
    evidence: dict[str, dict[str, Any]] = {}

    for sdir in strategy_dirs:
        if not sdir.is_dir():
            continue

        # Group strategy files by concept (latest version wins)
        concept_files: dict[str, Path] = {}
        for f in sorted(sdir.glob("*_v*.json")):
            # e.g., "neg_cov_debt_general_basket_v3.json"
            stem = f.stem
            parts = stem.rsplit("_v", 1)
            if len(parts) == 2:
                concept_id = parts[0]
                concept_files[concept_id] = f  # Latest wins (sorted)

        for concept_id, fpath in concept_files.items():
            try:
                raw = fpath.read_text()
                data = json.loads(raw)
            except (json.JSONDecodeError, OSError):
                continue

            if concept_id not in evidence:
                evidence[concept_id] = {
                    "sections": Counter(),
                    "articles": Counter(),
                    "headings": [],
                    "n_strategies": 0,
                    "best_score": 0.0,
                }

            entry = evidence[concept_id]
            entry["n_strategies"] += 1

            # Extract section/article location data from strategy
            for key in ("heading_patterns", "headings", "heading"):
                val = data.get(key)
                if isinstance(val, list):
                    entry["headings"].extend(val)
                elif isinstance(val, str) and val:
                    entry["headings"].append(val)

            # Extract section hit evidence
            if "hits" in data and isinstance(data["hits"], list):
                for hit in data["hits"]:
                    sec = hit.get("section_number", "")
                    if sec:
                        entry["sections"][sec] += 1
                    art = hit.get("article_num", 0)
                    if art:
                        entry["articles"][str(art)] += 1

            # Extract score
            score = data.get("score", data.get("f1", 0.0))
            if isinstance(score, (int, float)):
                entry["best_score"] = max(entry["best_score"], float(score))

    return evidence


# ---------------------------------------------------------------------------
# Corpus query — section prevalence from DuckDB
# ---------------------------------------------------------------------------


def query_section_prevalence(
    db_path: Path,
) -> dict[str, Counter[str]]:
    """Query corpus index for section heading → section number distribution.

    Returns: {normalized_heading: Counter({section_number: count})}
    """
    try:
        import duckdb
    except ImportError:
        log("WARNING: duckdb not installed, skipping corpus query")
        return {}

    if not db_path.exists():
        log(f"WARNING: corpus index not found at {db_path}")
        return {}

    heading_sections: dict[str, Counter[str]] = defaultdict(Counter)

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        # Query section headings and numbers
        rows = con.execute("""
            SELECT section_number, heading
            FROM sections
            WHERE heading IS NOT NULL AND heading != ''
              AND section_number IS NOT NULL AND section_number != ''
        """).fetchall()
        con.close()

        for sec_num, heading in rows:
            norm = heading.strip().lower()
            heading_sections[norm][sec_num] += 1

    except Exception as e:
        log(f"WARNING: corpus query failed: {e}")

    return heading_sections


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_section_map(
    strategy_evidence: dict[str, dict[str, Any]],
    corpus_prevalence: dict[str, Counter[str]],
) -> list[dict[str, Any]]:
    """Build the unified section map with HHI stability."""
    results: list[dict[str, Any]] = []

    for concept_id, ev in sorted(strategy_evidence.items()):
        sections = ev["sections"]
        headings = ev["headings"]
        articles = ev["articles"]

        # Enrich from corpus prevalence: match headings to corpus data
        for h in headings:
            norm_h = h.strip().lower()
            if norm_h in corpus_prevalence:
                for sec_num, count in corpus_prevalence[norm_h].items():
                    sections[sec_num] += count

        stability = compute_hhi(sections)
        strategy = location_strategy(stability)

        # Top section numbers by frequency
        top_sections = sections.most_common(5)

        # Article range
        art_nums = sorted(int(a) for a in articles if a.isdigit())
        article_range = {
            "min": min(art_nums) if art_nums else 0,
            "max": max(art_nums) if art_nums else 0,
        }

        # Unique headings (deduped, case-insensitive)
        seen: set[str] = set()
        unique_headings: list[str] = []
        for h in headings:
            key = h.strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique_headings.append(h.strip())

        results.append({
            "concept_id": concept_id,
            "n_strategies": ev["n_strategies"],
            "best_score": round(ev["best_score"], 4),
            "stability_score": round(stability, 4),
            "location_strategy": strategy,
            "top_sections": [
                {"number": num, "count": cnt} for num, cnt in top_sections
            ],
            "article_range": article_range,
            "headings": unique_headings[:10],
            "total_section_hits": sum(sections.values()),
        })

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile per-concept section location map with HHI stability."
    )
    parser.add_argument(
        "--db", type=Path, default=Path("corpus_index/corpus.duckdb"),
        help="Path to DuckDB corpus index",
    )
    parser.add_argument(
        "--strategies", type=str, nargs="+", default=[],
        help="Glob patterns for strategy directories (e.g., workspaces/*/strategies/)",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write output to file instead of stdout",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show summary without writing output",
    )
    args = parser.parse_args()

    # Resolve strategy directories from glob patterns
    strategy_dirs: list[Path] = []
    for pattern in args.strategies:
        for match in sorted(glob.glob(pattern)):
            p = Path(match)
            if p.is_dir():
                strategy_dirs.append(p)

    log(f"Loading strategy evidence from {len(strategy_dirs)} directories...")
    strategy_evidence = load_strategy_evidence(strategy_dirs)
    log(f"  Found {len(strategy_evidence)} concepts with strategy evidence")

    log(f"Querying corpus prevalence from {args.db}...")
    corpus_prevalence = query_section_prevalence(args.db)
    log(f"  Found {len(corpus_prevalence)} distinct section headings")

    section_map = build_section_map(strategy_evidence, corpus_prevalence)

    # Summary stats
    high_stability = sum(1 for e in section_map if e["stability_score"] >= 0.7)
    medium_stability = sum(1 for e in section_map if 0.3 <= e["stability_score"] < 0.7)
    low_stability = sum(1 for e in section_map if e["stability_score"] < 0.3)

    log(f"\nSection Map Summary:")
    log(f"  Total concepts: {len(section_map)}")
    log(f"  High stability (≥0.7): {high_stability}")
    log(f"  Medium stability (0.3-0.7): {medium_stability}")
    log(f"  Low stability (<0.3): {low_stability}")

    if args.dry_run:
        log("\n[DRY RUN] Would write section map. Top 10 by stability:")
        for entry in sorted(section_map, key=lambda e: -e["stability_score"])[:10]:
            log(f"  {entry['concept_id']}: stability={entry['stability_score']:.2f} "
                f"strategy={entry['location_strategy']} "
                f"sections={entry['total_section_hits']}")
        return

    output = {
        "version": "1.0",
        "n_concepts": len(section_map),
        "stability_distribution": {
            "high": high_stability,
            "medium": medium_stability,
            "low": low_stability,
        },
        "concepts": section_map,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2, default=str))
        log(f"\nWrote section map to {args.output}")
    else:
        dump_json(output)


if __name__ == "__main__":
    main()
