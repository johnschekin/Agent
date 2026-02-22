#!/usr/bin/env python3
"""Full-text pattern search across the corpus index.

Searches section text for a given pattern (substring match) and returns
structured JSON results to stdout with summary messages to stderr.

Usage:
    python3 scripts/corpus_search.py --db corpus_index/corpus.duckdb \
      --pattern "Limitation on Indebtedness" --context-chars 200 --max-results 50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


from agent.corpus import CorpusIndex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Full-text pattern search across the corpus index."
    )
    parser.add_argument(
        "--db", required=True, type=Path, help="Path to corpus.duckdb"
    )
    parser.add_argument(
        "--pattern", required=True, help="Search pattern (substring match)"
    )
    parser.add_argument(
        "--context-chars",
        type=int,
        default=200,
        help="Context characters around match (default: 200)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=50,
        help="Maximum number of results (default: 50)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Only search in N random docs (for speed)",
    )
    parser.add_argument(
        "--doc-ids",
        type=Path,
        default=None,
        help="File with doc IDs to restrict search (one per line)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if not args.db.exists():
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    with CorpusIndex(args.db) as corpus:
        # Determine doc_ids restriction
        doc_ids: list[str] | None = None

        if args.doc_ids is not None:
            doc_ids_path: Path = args.doc_ids
            if not doc_ids_path.exists():
                print(
                    f"Error: doc-ids file not found: {doc_ids_path}",
                    file=sys.stderr,
                )
                sys.exit(1)
            doc_ids = [
                line.strip()
                for line in doc_ids_path.read_text().splitlines()
                if line.strip()
            ]
            print(
                f"Restricting search to {len(doc_ids)} doc IDs from {doc_ids_path}",
                file=sys.stderr,
            )

        if args.sample is not None:
            sampled = corpus.sample_docs(args.sample)
            if doc_ids is not None:
                # Intersect: only keep sampled docs that are also in the file
                sampled_set = set(sampled)
                doc_ids = [d for d in doc_ids if d in sampled_set]
            else:
                doc_ids = sampled
            print(
                f"Sampled {len(doc_ids)} documents for search",
                file=sys.stderr,
            )

        results = corpus.search_text(
            args.pattern,
            context_chars=args.context_chars,
            max_results=args.max_results,
            doc_ids=doc_ids,
        )

        # Compute distinct doc count
        unique_docs = {r["doc_id"] for r in results}
        print(
            f"Found {len(results)} matches across {len(unique_docs)} documents",
            file=sys.stderr,
        )

        dump_json(results)


if __name__ == "__main__":
    main()
