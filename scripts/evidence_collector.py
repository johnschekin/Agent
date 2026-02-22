#!/usr/bin/env python3
"""Save matched spans with provenance to workspace evidence files.

Usage:
    python3 scripts/evidence_collector.py \\
      --matches matches.json \\
      --concept-id debt_capacity.indebtedness \\
      --workspace workspaces/indebtedness

Outputs structured JSON to stdout, human messages to stderr.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def dump_json_bytes(obj: object) -> bytes:
        return orjson.dumps(obj, default=str)

    def load_json(path: Path) -> object:
        return orjson.loads(path.read_bytes())
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def dump_json_bytes(obj: object) -> bytes:
        return json.dumps(obj, default=str).encode("utf-8")

    def load_json(path: Path) -> object:
        with open(path) as f:
            return json.load(f)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save matched spans with provenance to workspace evidence files."
    )
    parser.add_argument(
        "--matches",
        required=True,
        help="JSON file with match results (output from pattern_tester or child_locator)",
    )
    parser.add_argument(
        "--concept-id", required=True, help="Concept ID for provenance tracking"
    )
    parser.add_argument(
        "--workspace", required=True, help="Workspace directory path"
    )
    args = parser.parse_args()

    matches_path = Path(args.matches)
    if not matches_path.exists():
        log(f"Error: matches file not found at {matches_path}")
        sys.exit(1)

    workspace = Path(args.workspace)
    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Load matches
    matches = load_json(matches_path)
    if not isinstance(matches, list):
        log("Error: matches must be a JSON array")
        sys.exit(1)

    log(f"Loaded {len(matches)} match(es) from {matches_path}")

    # Generate timestamp for filename
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    evidence_filename = f"{args.concept_id}_{timestamp}.jsonl"
    evidence_file = evidence_dir / evidence_filename

    # Required fields (flexible: accept both char_start/span_start naming)
    records_written = 0
    unique_docs: set[str] = set()
    skipped = 0

    with open(evidence_file, "wb") as f:
        for i, match in enumerate(matches):
            doc_id = match.get("doc_id")
            if not doc_id:
                log(f"Warning: match {i} missing doc_id, skipping")
                skipped += 1
                continue

            # Resolve char_start / span_start
            char_start = match.get("char_start") or match.get("span_start")
            char_end = match.get("char_end") or match.get("span_end")

            if char_start is None or char_end is None:
                log(f"Warning: match {i} (doc_id={doc_id}) missing start/end offsets, skipping")
                skipped += 1
                continue

            record = {
                "doc_id": doc_id,
                "concept_id": args.concept_id,
                "char_start": char_start,
                "char_end": char_end,
                "match_type": match.get("match_type", "unknown"),
                "score": match.get("score") or match.get("match_score") or match.get("confidence"),
                "section_number": match.get("section_number") or match.get("parent_section", ""),
                "clause_path": match.get("clause_path", ""),
            }

            f.write(dump_json_bytes(record))
            f.write(b"\n")
            records_written += 1
            unique_docs.add(doc_id)

    if skipped > 0:
        log(f"Skipped {skipped} match(es) with missing required fields")

    log(f"Wrote {records_written} evidence record(s) for {len(unique_docs)} unique doc(s)")

    summary = {
        "concept_id": args.concept_id,
        "evidence_file": str(evidence_file),
        "records_written": records_written,
        "unique_docs": len(unique_docs),
    }
    dump_json(summary)


if __name__ == "__main__":
    main()
