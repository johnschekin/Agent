#!/usr/bin/env python3
"""Build a corpus heading super-graph for long-tail diagnostics.

P2 baseline inspired by TI round7_super_graph:
- nodes: normalized section headings
- edges: within-document co-occurrence
- ghost candidates: high-frequency headings not in canonical alias index
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import orjson

    def dump_json(obj: Any) -> None:
        import sys

        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: Any) -> None:
        print(json.dumps(obj, indent=2, default=str))


from agent.corpus import CorpusIndex


def _norm_heading(heading: str) -> str:
    return " ".join((heading or "").lower().split())


def _load_aliases(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    raw = json.loads(path.read_text())
    aliases: set[str] = set()
    records: list[dict[str, Any]] = []
    if isinstance(raw, dict) and "strategies" in raw and isinstance(raw["strategies"], list):
        records = [r for r in raw["strategies"] if isinstance(r, dict)]
    elif isinstance(raw, dict):
        records = [r for r in raw.values() if isinstance(r, dict)]
    for rec in records:
        name = rec.get("name")
        if isinstance(name, str):
            aliases.add(_norm_heading(name))
        strategy = rec.get("search_strategy")
        if isinstance(strategy, dict):
            headings = strategy.get("heading_patterns", [])
            if isinstance(headings, list):
                for h in headings:
                    if isinstance(h, str):
                        aliases.add(_norm_heading(h))
    return {a for a in aliases if a}


def run(args: argparse.Namespace) -> None:
    with CorpusIndex(Path(args.db)) as corpus:
        if args.sample:
            doc_ids = corpus.sample_docs(
                args.sample,
                seed=args.seed,
                cohort_only=not args.include_all,
            )
        else:
            doc_ids = corpus.doc_ids(cohort_only=not args.include_all)

        node_counts: Counter[str] = Counter()
        edge_counts: Counter[tuple[str, str]] = Counter()

        for doc_id in doc_ids:
            sections = corpus.search_sections(
                doc_id=doc_id,
                cohort_only=not args.include_all,
                limit=9999,
            )
            headings = sorted({_norm_heading(sec.heading) for sec in sections if sec.heading.strip()})
            for heading in headings:
                node_counts[heading] += 1
            for i in range(len(headings)):
                for j in range(i + 1, len(headings)):
                    edge_counts[(headings[i], headings[j])] += 1

    aliases = _load_aliases(Path(args.canonical_bootstrap) if args.canonical_bootstrap else None)
    ghost_candidates = [
        {"heading": heading, "frequency": count}
        for heading, count in node_counts.most_common()
        if count >= args.ghost_min_frequency and heading not in aliases
    ][: args.top_n]

    nodes = [
        {"id": heading, "frequency": count, "in_canonical_registry": heading in aliases}
        for heading, count in node_counts.most_common(args.top_n)
    ]
    edges = [
        {"source": src, "target": dst, "weight": weight}
        for (src, dst), weight in edge_counts.most_common(args.top_n * 5)
        if weight >= args.min_edge_weight
    ]

    degree: defaultdict[str, int] = defaultdict(int)
    for edge in edges:
        degree[str(edge["source"])] += int(edge["weight"])
        degree[str(edge["target"])] += int(edge["weight"])
    hubs = sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))[: args.top_n]

    dump_json(
        {
            "status": "ok",
            "documents": len(doc_ids),
            "node_count": len(node_counts),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
            "hubs": [{"heading": h, "weighted_degree": d} for h, d in hubs],
            "ghost_candidates": ghost_candidates,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Heading super-graph analyzer.")
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument("--sample", type=int, default=None, help="Optional random sample size")
    parser.add_argument("--seed", type=int, default=42, help="Sample seed")
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default cohort-only).",
    )
    parser.add_argument(
        "--canonical-bootstrap",
        default=None,
        help="Optional bootstrap_all.json path for canonical alias matching.",
    )
    parser.add_argument("--top-n", type=int, default=100, help="Top nodes/hubs to emit")
    parser.add_argument("--min-edge-weight", type=int, default=3, help="Edge weight threshold")
    parser.add_argument(
        "--ghost-min-frequency",
        type=int,
        default=8,
        help="Minimum heading frequency for ghost candidate reporting.",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()

