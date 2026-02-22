#!/usr/bin/env python3
"""Stratified sample selection for testing.

Selects a random sample of documents from the corpus index, with optional
stratification by a metadata column. Outputs structured JSON to stdout or
writes doc IDs to a file.

Usage:
    python3 scripts/sample_selector.py --db corpus_index/corpus.duckdb \
      --n 200 --stratify template_family --seed 42 --output sample.txt
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
        description="Stratified sample selection for testing."
    )
    parser.add_argument(
        "--db", required=True, type=Path, help="Path to corpus.duckdb"
    )
    parser.add_argument(
        "--n", required=True, type=int, help="Number of documents to sample"
    )
    parser.add_argument(
        "--stratify",
        default=None,
        help="Column to stratify by (e.g., 'template_family')",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed (default: 42)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write doc IDs to file (one per line). If omitted, JSON to stdout.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if not args.db.exists():
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    with CorpusIndex(args.db) as corpus:
        total_docs = corpus.doc_count

        if args.n > total_docs:
            print(
                f"Warning: requested {args.n} docs but corpus only has "
                f"{total_docs}. Returning all.",
                file=sys.stderr,
            )

        # Sample doc IDs
        sampled_ids = corpus.sample_docs(
            args.n,
            seed=args.seed,
            stratify_by=args.stratify,
        )

        # Fetch full records to build output
        records: list[dict[str, object]] = []
        for doc_id in sampled_ids:
            doc = corpus.get_doc(doc_id)
            if doc is None:
                continue
            records.append({
                "doc_id": doc.doc_id,
                "template_family": doc.template_family,
                "section_count": doc.section_count,
                "text_length": doc.text_length,
            })

        if args.output is not None:
            # Write doc IDs to file, one per line
            output_path: Path = args.output
            output_path.write_text(
                "\n".join(r["doc_id"] for r in records) + "\n"  # type: ignore[arg-type]
            )
            print(
                f"Wrote {len(records)} doc IDs to {output_path}",
                file=sys.stderr,
            )
            # Also print summary to stderr
            if args.stratify:
                # Count per stratum
                strata: dict[str, int] = {}
                for r in records:
                    key = str(r.get("template_family", "unknown"))
                    strata[key] = strata.get(key, 0) + 1
                print(f"Stratification by {args.stratify}:", file=sys.stderr)
                for k, v in sorted(strata.items()):
                    print(f"  {k}: {v}", file=sys.stderr)
        else:
            # JSON to stdout
            print(
                f"Selected {len(records)} documents from {total_docs} total"
                + (f" (stratified by {args.stratify})" if args.stratify else ""),
                file=sys.stderr,
            )
            dump_json(records)


if __name__ == "__main__":
    main()
