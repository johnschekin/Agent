#!/usr/bin/env python3
"""Prepare manual adjudication packets from unresolved queue rows.

This script does not generate labels or reasoning. It only selects rows
for manual adjudication packets based on deterministic filtering.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            rows.append(obj)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _parse_quotas(raw: str) -> dict[str, int]:
    quotas: dict[str, int] = {}
    text = str(raw or "").strip()
    if not text:
        return quotas
    for token in [piece.strip() for piece in text.split(",") if piece.strip()]:
        if ":" not in token:
            raise ValueError(f"Invalid quota token '{token}', expected category:count")
        key, value = token.split(":", 1)
        category = key.strip()
        count = int(value.strip())
        if not category:
            raise ValueError(f"Invalid empty category in quota token '{token}'")
        if count < 0:
            raise ValueError(f"Invalid negative count in quota token '{token}'")
        quotas[category] = count
    return quotas


def _priority_key(row: dict[str, Any], priority_field: str, id_field: str) -> tuple[int, str]:
    raw_rank = row.get(priority_field)
    rank = 10**9
    if isinstance(raw_rank, int):
        rank = raw_rank
    elif isinstance(raw_rank, str) and raw_rank.strip().isdigit():
        rank = int(raw_rank.strip())
    row_id = str(row.get(id_field) or "").strip()
    return rank, row_id


def _extract_adjudicated_ids(paths: list[Path], id_field: str) -> set[str]:
    ids: set[str] = set()
    for path in paths:
        for row in _load_jsonl(path):
            row_id = str(row.get(id_field) or row.get("row_id") or "").strip()
            if row_id:
                ids.add(row_id)
    return ids


def _select_packet_rows(
    unresolved: list[dict[str, Any]],
    *,
    batch_size: int,
    quotas: dict[str, int],
    category_field: str,
    priority_field: str,
    id_field: str,
) -> list[dict[str, Any]]:
    ordered = sorted(unresolved, key=lambda row: _priority_key(row, priority_field, id_field))
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    if quotas:
        by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in ordered:
            by_category[str(row.get(category_field) or "").strip()].append(row)
        for category, target in quotas.items():
            if target <= 0:
                continue
            for row in by_category.get(category, [])[:target]:
                row_id = str(row.get(id_field) or "").strip()
                if not row_id or row_id in selected_ids:
                    continue
                selected.append(row)
                selected_ids.add(row_id)
                if len(selected) >= batch_size:
                    return selected

    for row in ordered:
        if len(selected) >= batch_size:
            break
        row_id = str(row.get(id_field) or "").strip()
        if not row_id or row_id in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(row_id)

    return selected


def _with_packet_metadata(rows: list[dict[str, Any]], *, batch_id: str) -> list[dict[str, Any]]:
    stamped: list[dict[str, Any]] = []
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    for idx, row in enumerate(rows, start=1):
        copied = dict(row)
        copied["packet_batch_id"] = batch_id
        copied["packet_position"] = idx
        copied["packet_prepared_at"] = now
        copied["manual_label_required"] = True
        copied["manual_reasoning_required"] = True
        stamped.append(copied)
    return stamped


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare manual adjudication packet JSONL")
    parser.add_argument("--queue", type=Path, required=True, help="Queue JSONL path")
    parser.add_argument(
        "--adjudicated-batch",
        action="append",
        type=Path,
        default=[],
        help="Adjudicated batch JSONL path to exclude by queue item id (repeatable)",
    )
    parser.add_argument("--batch-id", required=True, help="Packet batch identifier")
    parser.add_argument("--batch-size", type=int, default=20, help="Packet size")
    parser.add_argument(
        "--category-quotas",
        default="",
        help="Optional category quotas category:count,...",
    )
    parser.add_argument(
        "--id-field",
        default="queue_item_id",
        help="Unique identifier field in queue and adjudication logs",
    )
    parser.add_argument("--category-field", default="category", help="Category field")
    parser.add_argument("--priority-field", default="priority_rank", help="Priority rank field")
    parser.add_argument("--out-packet", type=Path, required=True, help="Packet JSONL output")
    parser.add_argument(
        "--out-remaining",
        type=Path,
        required=True,
        help="Remaining unresolved queue JSONL output",
    )
    parser.add_argument("--out-summary", type=Path, required=True, help="Summary JSON output")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be > 0")

    queue_rows = _load_jsonl(args.queue)
    adjudicated_ids = _extract_adjudicated_ids(args.adjudicated_batch, args.id_field)

    unresolved = [
        row
        for row in queue_rows
        if str(row.get(args.id_field) or "").strip()
        and str(row.get(args.id_field) or "").strip() not in adjudicated_ids
    ]
    unresolved_sorted = sorted(
        unresolved,
        key=lambda row: _priority_key(row, args.priority_field, args.id_field),
    )

    quotas = _parse_quotas(args.category_quotas)
    packet = _select_packet_rows(
        unresolved_sorted,
        batch_size=args.batch_size,
        quotas=quotas,
        category_field=args.category_field,
        priority_field=args.priority_field,
        id_field=args.id_field,
    )
    packet_ids = {
        str(row.get(args.id_field) or "").strip()
        for row in packet
        if str(row.get(args.id_field) or "").strip()
    }
    remaining_after_packet = [
        row
        for row in unresolved_sorted
        if str(row.get(args.id_field) or "").strip() not in packet_ids
    ]

    packet_with_meta = _with_packet_metadata(packet, batch_id=args.batch_id)
    _write_jsonl(args.out_packet, packet_with_meta)
    _write_jsonl(args.out_remaining, remaining_after_packet)

    summary = {
        "schema_version": "manual-adjudication-packet-summary-v1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "batch_id": args.batch_id,
        "queue_path": str(args.queue),
        "batch_size_requested": args.batch_size,
        "batch_size_selected": len(packet_with_meta),
        "category_quotas_requested": quotas,
        "adjudicated_rows_excluded": len(adjudicated_ids),
        "unresolved_before_packet": len(unresolved_sorted),
        "remaining_after_packet": len(remaining_after_packet),
        "packet_category_counts": dict(
            Counter(str(row.get(args.category_field) or "").strip() for row in packet_with_meta),
        ),
        "packet_split_counts": dict(
            Counter(str(row.get("split") or "").strip() for row in packet_with_meta),
        ),
        "unresolved_category_counts": dict(
            Counter(str(row.get(args.category_field) or "").strip() for row in unresolved_sorted),
        ),
        "unresolved_split_counts": dict(
            Counter(str(row.get("split") or "").strip() for row in unresolved_sorted),
        ),
    }
    args.out_summary.parent.mkdir(parents=True, exist_ok=True)
    args.out_summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "ok",
                "batch_id": args.batch_id,
                "selected": len(packet_with_meta),
                "remaining": len(remaining_after_packet),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
