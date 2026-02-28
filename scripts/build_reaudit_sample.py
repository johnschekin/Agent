#!/usr/bin/env python3
"""Build a deterministic re-audit sample scaffold from adjudication batches."""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "manual-reaudit-sample-v1"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no}: row must be JSON object")
            rows.append(payload)
    return rows


def _dedupe_rows(batch_paths: list[Path]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for batch_path in batch_paths:
        for row in _load_jsonl(batch_path):
            row_id = str(row.get("row_id") or "").strip()
            if not row_id or row_id in seen:
                continue
            seen.add(row_id)
            row_copy = dict(row)
            row_copy["_source_batch_path"] = str(batch_path)
            ordered.append(row_copy)
    return ordered


def _build_sample(
    *,
    rows: list[dict[str, Any]],
    ratio: float,
    min_sample_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    sample_size = max(min_sample_size, math.ceil(len(rows) * ratio))
    sample_size = min(sample_size, len(rows))
    rng = random.Random(seed)
    chosen = rng.sample(rows, sample_size)
    chosen.sort(key=lambda row: str(row.get("row_id") or ""))
    generated_at = datetime.now(UTC).isoformat()

    output: list[dict[str, Any]] = []
    for index, row in enumerate(chosen, start=1):
        output.append(
            {
                "schema_version": SCHEMA_VERSION,
                "reaudit_item_id": f"REAUDIT-{index:04d}",
                "row_id": str(row.get("row_id") or "").strip(),
                "queue_item_id": str(row.get("queue_item_id") or "").strip(),
                "source_batch_path": str(row.get("_source_batch_path") or "").strip(),
                "original_decision": str(row.get("decision") or "").strip(),
                "original_confidence_level": str(row.get("confidence_level") or "").strip(),
                "re_audit_decision": "",
                "agreement": "",
                "disagreement_reason": "",
                "review_notes": "",
                "created_at": generated_at,
            }
        )
    return output


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic re-audit sample scaffold from adjudication "
            "JSONL batches."
        )
    )
    parser.add_argument(
        "--batch",
        action="append",
        required=True,
        type=Path,
        help="Path to adjudication batch JSONL file (repeatable).",
    )
    parser.add_argument(
        "--sample-ratio",
        type=float,
        default=0.1,
        help="Sample ratio from total rows (default: 0.10).",
    )
    parser.add_argument(
        "--min-sample-size",
        type=int,
        default=1,
        help="Minimum sample size (default: 1).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260227,
        help="Deterministic RNG seed (default: 20260227).",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output JSONL scaffold path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sample_ratio <= 0.0 or args.sample_ratio > 1.0:
        raise SystemExit("--sample-ratio must be > 0 and <= 1")
    if args.min_sample_size < 1:
        raise SystemExit("--min-sample-size must be >= 1")
    batch_paths = [path.resolve() for path in args.batch]
    for batch_path in batch_paths:
        if not batch_path.exists():
            raise SystemExit(f"batch not found: {batch_path}")
    rows = _dedupe_rows(batch_paths)
    sample_rows = _build_sample(
        rows=rows,
        ratio=args.sample_ratio,
        min_sample_size=args.min_sample_size,
        seed=args.seed,
    )
    _write_jsonl(args.out.resolve(), sample_rows)
    summary = {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "input_batches": [str(path) for path in batch_paths],
        "input_row_count": len(rows),
        "sample_row_count": len(sample_rows),
        "sample_ratio": args.sample_ratio,
        "min_sample_size": args.min_sample_size,
        "seed": args.seed,
        "output_path": str(args.out.resolve()),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
