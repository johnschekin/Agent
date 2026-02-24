#!/usr/bin/env python3
"""Promote checkpoint status for families in a wave using artifact criteria.

This tool is intended for rollout governance once a wave has produced baseline
strategy/evidence artifacts and is ready for transition gating.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Assignment:
    family: str
    pane: int
    wave: int
    backend: str
    whitelist: str
    dependencies: tuple[str, ...]


def _parse_swarm_conf(conf_path: Path) -> list[Assignment]:
    assignments: list[Assignment] = []
    if not conf_path.exists():
        return assignments
    for line in conf_path.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "|" not in raw or "=" in raw:
            continue
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 5:
            continue
        try:
            pane = int(parts[1])
            wave = int(parts[2])
        except ValueError:
            continue
        deps: tuple[str, ...] = ()
        if len(parts) >= 6 and parts[5]:
            deps = tuple(v.strip() for v in parts[5].split(",") if v.strip())
        assignments.append(
            Assignment(
                family=parts[0],
                pane=pane,
                wave=wave,
                backend=parts[3],
                whitelist=parts[4],
                dependencies=deps,
            )
        )
    return assignments


def _read_checkpoint(path: Path) -> tuple[str, dict[str, Any]]:
    if not path.exists():
        return "missing", {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return "invalid", {}
    if not isinstance(payload, dict):
        return "invalid", {}
    status = str(payload.get("status", "")).strip().lower() or "initialized"
    return status, payload


def _count_jsonl_records(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _collect_workspace_stats(workspace_root: Path, family: str) -> dict[str, Any]:
    root = workspace_root / family
    strategies_dir = root / "strategies"
    evidence_dir = root / "evidence"
    results_dir = root / "results"

    strategy_files = sorted(
        fp for fp in strategies_dir.glob("*_v*.json") if fp.is_file()
    ) if strategies_dir.exists() else []
    evidence_files = sorted(evidence_dir.glob("*.jsonl")) if evidence_dir.exists() else []
    result_files = sorted(results_dir.glob("*.json")) if results_dir.exists() else []

    record_count = 0
    for fp in evidence_files:
        try:
            record_count += _count_jsonl_records(fp)
        except OSError:
            continue

    latest_strategy = max(strategy_files, key=lambda fp: fp.stat().st_mtime) if strategy_files else None
    latest_evidence = max(evidence_files, key=lambda fp: fp.stat().st_mtime) if evidence_files else None
    latest_result = max(result_files, key=lambda fp: fp.stat().st_mtime) if result_files else None

    return {
        "strategy_version_file_count": len(strategy_files),
        "evidence_file_count": len(evidence_files),
        "evidence_record_count": int(record_count),
        "result_json_file_count": len(result_files),
        "latest_strategy_file": str(latest_strategy) if latest_strategy else "",
        "latest_evidence_file": str(latest_evidence) if latest_evidence else "",
        "latest_result_file": str(latest_result) if latest_result else "",
    }


def _eligible(
    *,
    stats: dict[str, Any],
    require_strategy: bool,
    require_evidence: bool,
    min_strategy_files: int,
    min_evidence_files: int,
    min_evidence_records: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    strategy_files = int(stats.get("strategy_version_file_count", 0))
    evidence_files = int(stats.get("evidence_file_count", 0))
    evidence_records = int(stats.get("evidence_record_count", 0))

    if require_strategy and strategy_files < min_strategy_files:
        reasons.append(
            f"strategy_version_file_count {strategy_files} < min_strategy_files {min_strategy_files}"
        )
    if require_evidence and evidence_files < min_evidence_files:
        reasons.append(
            f"evidence_file_count {evidence_files} < min_evidence_files {min_evidence_files}"
        )
    if require_evidence and evidence_records < min_evidence_records:
        reasons.append(
            f"evidence_record_count {evidence_records} < min_evidence_records {min_evidence_records}"
        )
    return len(reasons) == 0, reasons


def _parse_csv(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote checkpoint status for families in a wave using artifact criteria.",
    )
    parser.add_argument("--conf", default="swarm/swarm.conf", help="Path to swarm config.")
    parser.add_argument(
        "--workspace-root",
        default="workspaces",
        help="Path to workspace root.",
    )
    parser.add_argument("--wave", type=int, required=True, help="Wave number to promote.")
    parser.add_argument(
        "--from-statuses",
        default="running",
        help="Comma-separated checkpoint statuses eligible for promotion.",
    )
    parser.add_argument(
        "--to-status",
        default="completed",
        help="Target checkpoint status (e.g., completed, locked).",
    )
    parser.add_argument(
        "--require-strategy",
        action="store_true",
        help="Require strategy artifacts before promotion.",
    )
    parser.add_argument(
        "--require-evidence",
        action="store_true",
        help="Require evidence artifacts before promotion.",
    )
    parser.add_argument(
        "--min-strategy-files",
        type=int,
        default=1,
        help="Minimum strategy version files when --require-strategy is set.",
    )
    parser.add_argument(
        "--min-evidence-files",
        type=int,
        default=1,
        help="Minimum evidence files when --require-evidence is set.",
    )
    parser.add_argument(
        "--min-evidence-records",
        type=int,
        default=1,
        help="Minimum evidence row count when --require-evidence is set.",
    )
    parser.add_argument(
        "--note",
        default="",
        help="Optional status note written into checkpoint payload.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate and report without writing checkpoint files.",
    )
    parser.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="Exit non-zero when any family fails promotion criteria.",
    )
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    conf_path = Path(args.conf)
    workspace_root = Path(args.workspace_root)
    from_statuses = _parse_csv(args.from_statuses)
    to_status = str(args.to_status).strip().lower()
    now = datetime.now(UTC).isoformat()

    assignments = [a for a in _parse_swarm_conf(conf_path) if a.wave == args.wave]
    rows: list[dict[str, Any]] = []
    promoted = 0
    blocked = 0
    skipped = 0

    for item in sorted(assignments, key=lambda a: (a.pane, a.family)):
        checkpoint_path = workspace_root / item.family / "checkpoint.json"
        status, payload = _read_checkpoint(checkpoint_path)
        stats = _collect_workspace_stats(workspace_root, item.family)

        eligible_status = status in from_statuses
        ok, reasons = _eligible(
            stats=stats,
            require_strategy=bool(args.require_strategy),
            require_evidence=bool(args.require_evidence),
            min_strategy_files=max(0, int(args.min_strategy_files)),
            min_evidence_files=max(0, int(args.min_evidence_files)),
            min_evidence_records=max(0, int(args.min_evidence_records)),
        )
        should_promote = eligible_status and ok

        action = "unchanged"
        if should_promote:
            action = "promoted"
            promoted += 1
            if not args.dry_run:
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                if not payload:
                    payload = {"family": item.family}
                payload["status"] = to_status
                payload["last_update"] = now
                payload["status_updated_at"] = now
                payload["status_updated_by"] = "wave_promote_status.py"
                if args.note:
                    payload["status_note"] = args.note
                checkpoint_path.write_text(json.dumps(payload, indent=2))
        else:
            if not eligible_status:
                skipped += 1
                if status == "missing":
                    reasons = reasons + ["checkpoint missing"]
                elif status == "invalid":
                    reasons = reasons + ["checkpoint invalid"]
                else:
                    reasons = reasons + [f"status '{status}' not in from_statuses"]
            else:
                blocked += 1

        row = {
            "family": item.family,
            "wave": item.wave,
            "pane": item.pane,
            "status_before": status,
            "status_after": to_status if should_promote else status,
            "eligible_status": eligible_status,
            "meets_criteria": ok,
            "action": action,
            "reasons": reasons,
            "checkpoint_path": str(checkpoint_path),
        }
        row.update(stats)
        rows.append(row)

    payload = {
        "schema_version": "wave_promote_status_v1",
        "generated_at": now,
        "config_path": str(conf_path),
        "workspace_root": str(workspace_root),
        "wave": args.wave,
        "from_statuses": sorted(from_statuses),
        "to_status": to_status,
        "criteria": {
            "require_strategy": bool(args.require_strategy),
            "require_evidence": bool(args.require_evidence),
            "min_strategy_files": int(args.min_strategy_files),
            "min_evidence_files": int(args.min_evidence_files),
            "min_evidence_records": int(args.min_evidence_records),
        },
        "dry_run": bool(args.dry_run),
        "summary": {
            "assignments": len(rows),
            "promoted_count": promoted,
            "blocked_count": blocked,
            "skipped_count": skipped,
        },
        "rows": rows,
    }

    blob = (
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if args.compact
        else json.dumps(payload, indent=2).encode("utf-8")
    )
    os.write(1, blob + b"\n")
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(blob + b"\n")
    if args.fail_on_blocked and blocked > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
