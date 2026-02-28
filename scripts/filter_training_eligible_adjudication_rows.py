#!/usr/bin/env python3
"""Filter adjudication rows to training-eligible subset and emit quarantine report."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NOISE_FLAGS = {"toc_or_index_noise", "ocr_noise", "index_noise", "garbled_span_noise"}


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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _is_quarantined(row: dict[str, Any]) -> tuple[bool, str]:
    eligible = row.get("training_export_eligible")
    if eligible is False:
        return True, "training_export_eligible=false"
    decision = str(row.get("decision") or "").strip().lower()
    allow_uncertain = bool(row.get("allow_uncertain_training_export", False))
    if decision in {"review", "abstain"} and not allow_uncertain:
        return True, f"decision={decision} requires explicit uncertain-export override"
    flags = row.get("quality_flags")
    if isinstance(flags, list):
        lowered = {str(flag).strip().lower() for flag in flags if str(flag).strip()}
        noisy = sorted(NOISE_FLAGS.intersection(lowered))
        if noisy:
            return True, f"quality_flags contains {','.join(noisy)}"
    return False, ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Filter adjudication rows to training-eligible subset and emit a "
            "quarantine report."
        )
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        type=Path,
        help="Input adjudication JSONL batch path (repeatable).",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output JSONL for training-eligible rows.",
    )
    parser.add_argument(
        "--quarantine-out",
        required=True,
        type=Path,
        help="Output JSON report with quarantined row metadata.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_paths = [path.resolve() for path in args.input]
    all_rows: list[dict[str, Any]] = []
    for path in input_paths:
        if not path.exists():
            raise SystemExit(f"input not found: {path}")
        all_rows.extend(_load_jsonl(path))

    eligible_rows: list[dict[str, Any]] = []
    quarantined: list[dict[str, str]] = []
    for row in all_rows:
        row_id = str(row.get("row_id") or "").strip()
        is_quarantined, reason = _is_quarantined(row)
        if is_quarantined:
            quarantined.append(
                {
                    "row_id": row_id,
                    "decision": str(row.get("decision") or "").strip(),
                    "reason": reason,
                }
            )
            continue
        eligible_rows.append(row)

    _write_jsonl(args.out.resolve(), eligible_rows)
    quarantine_payload = {
        "schema_version": "adjudication-training-quarantine-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "input_paths": [str(path) for path in input_paths],
        "total_rows": len(all_rows),
        "eligible_rows": len(eligible_rows),
        "quarantined_rows": len(quarantined),
        "quarantine": quarantined,
    }
    args.quarantine_out.parent.mkdir(parents=True, exist_ok=True)
    args.quarantine_out.write_text(
        json.dumps(quarantine_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(quarantine_payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
