#!/usr/bin/env python3
"""Emit per-family strategy/evidence/judge artifact manifests for swarm runs."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import orjson

    def _dumps(obj: Any, *, indent: bool) -> bytes:
        option = orjson.OPT_INDENT_2 if indent else 0
        return orjson.dumps(obj, option=option)
except ImportError:

    def _dumps(obj: Any, *, indent: bool) -> bytes:
        text = json.dumps(obj, indent=2 if indent else None, default=str)
        return text.encode("utf-8")


@dataclass(frozen=True, slots=True)
class Assignment:
    family: str
    pane: int
    wave: int
    backend: str
    whitelist: str
    dependencies: tuple[str, ...]


_VERSION_FILE_PATTERN = re.compile(r"_v\d+\.json$")
_RAW_VIEW_PATTERN = re.compile(r"_v\d+\.raw\.json$")
_RESOLVED_VIEW_PATTERN = re.compile(r"_v\d+\.resolved\.json$")
_JUDGE_PATTERN = re.compile(r"_v\d+\.judge\.json$")


def _parse_swarm_conf(conf_path: Path) -> tuple[dict[str, str], list[Assignment]]:
    defaults: dict[str, str] = {}
    assignments: list[Assignment] = []
    if not conf_path.exists():
        return defaults, assignments

    for line in conf_path.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "|" in raw:
            parts = [part.strip() for part in raw.split("|")]
            if len(parts) < 5:
                continue
            family = parts[0]
            try:
                pane = int(parts[1])
                wave = int(parts[2])
            except ValueError:
                continue
            backend = parts[3]
            whitelist = parts[4]
            deps: tuple[str, ...] = ()
            if len(parts) >= 6 and parts[5]:
                deps = tuple(v.strip() for v in parts[5].split(",") if v.strip())
            assignments.append(
                Assignment(
                    family=family,
                    pane=pane,
                    wave=wave,
                    backend=backend,
                    whitelist=whitelist,
                    dependencies=deps,
                )
            )
            continue
        if "=" in raw:
            key, value = raw.split("=", 1)
            defaults[key.strip()] = value.strip()
    return defaults, assignments


def _parse_dt(raw: str) -> datetime | None:
    value = str(raw).strip()
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _read_checkpoint(workspace_root: Path, family: str) -> tuple[str, dict[str, Any], Path]:
    fp = workspace_root / family / "checkpoint.json"
    if not fp.exists():
        return "missing", {}, fp
    try:
        payload = json.loads(fp.read_text())
    except json.JSONDecodeError:
        return "invalid", {}, fp
    if not isinstance(payload, dict):
        return "invalid", {}, fp
    status = str(payload.get("status", "")).strip().lower() or "initialized"
    return status, payload, fp


def _latest_path(files: list[Path]) -> Path | None:
    if not files:
        return None
    return max(files, key=lambda fp: fp.stat().st_mtime)


def _count_jsonl_records(path: Path) -> int:
    count = 0
    with path.open("rb") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _family_artifacts(workspace_root: Path, family: str) -> dict[str, Any]:
    root = workspace_root / family
    strategies_dir = root / "strategies"
    evidence_dir = root / "evidence"
    results_dir = root / "results"

    strategy_files = (
        sorted(
            fp
            for fp in strategies_dir.glob("*.json")
            if _VERSION_FILE_PATTERN.search(fp.name)
            and not _RAW_VIEW_PATTERN.search(fp.name)
            and not _RESOLVED_VIEW_PATTERN.search(fp.name)
            and not _JUDGE_PATTERN.search(fp.name)
        )
        if strategies_dir.exists()
        else []
    )
    raw_view_files = (
        sorted(fp for fp in strategies_dir.glob("*.raw.json"))
        if strategies_dir.exists()
        else []
    )
    resolved_view_files = (
        sorted(fp for fp in strategies_dir.glob("*.resolved.json"))
        if strategies_dir.exists()
        else []
    )
    judge_files = (
        sorted(fp for fp in strategies_dir.glob("*.judge.json"))
        if strategies_dir.exists()
        else []
    )
    evidence_files = sorted(evidence_dir.glob("*.jsonl")) if evidence_dir.exists() else []
    result_files = sorted(results_dir.glob("*.json")) if results_dir.exists() else []

    latest_strategy = _latest_path(strategy_files)
    latest_raw = _latest_path(raw_view_files)
    latest_resolved = _latest_path(resolved_view_files)
    latest_judge = _latest_path(judge_files)
    latest_evidence = _latest_path(evidence_files)
    latest_result = _latest_path(result_files)

    evidence_record_count = 0
    latest_evidence_records = 0
    for fp in evidence_files:
        recs = _count_jsonl_records(fp)
        evidence_record_count += recs
        if latest_evidence is not None and fp == latest_evidence:
            latest_evidence_records = recs

    latest_artifact_dt = None
    for fp in (
        [latest_strategy, latest_raw, latest_resolved, latest_judge, latest_evidence, latest_result]
    ):
        if fp is None:
            continue
        dt = datetime.fromtimestamp(fp.stat().st_mtime, tz=UTC)
        if latest_artifact_dt is None or dt > latest_artifact_dt:
            latest_artifact_dt = dt

    return {
        "strategy_version_file_count": len(strategy_files),
        "strategy_raw_view_count": len(raw_view_files),
        "strategy_resolved_view_count": len(resolved_view_files),
        "judge_report_count": len(judge_files),
        "evidence_file_count": len(evidence_files),
        "evidence_record_count": evidence_record_count,
        "result_json_file_count": len(result_files),
        "latest_strategy_file": str(latest_strategy) if latest_strategy else "",
        "latest_strategy_raw_file": str(latest_raw) if latest_raw else "",
        "latest_strategy_resolved_file": str(latest_resolved) if latest_resolved else "",
        "latest_judge_file": str(latest_judge) if latest_judge else "",
        "latest_evidence_file": str(latest_evidence) if latest_evidence else "",
        "latest_evidence_record_count": latest_evidence_records,
        "latest_result_file": str(latest_result) if latest_result else "",
        "latest_artifact_at": latest_artifact_dt.isoformat() if latest_artifact_dt else "",
    }


def _family_state(
    *,
    checkpoint_status: str,
    strategy_count: int,
    evidence_count: int,
) -> str:
    if checkpoint_status in {"completed", "locked"}:
        return "completed"
    if checkpoint_status in {"failed", "error", "stalled"}:
        return "attention_needed"
    if checkpoint_status == "missing" and strategy_count == 0 and evidence_count == 0:
        return "unstarted"
    if strategy_count > 0 and evidence_count > 0:
        return "review_ready"
    if checkpoint_status == "running":
        return "in_progress"
    return "partial"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate per-family swarm artifact manifest snapshots."
    )
    parser.add_argument("--conf", default="swarm/swarm.conf", help="Path to swarm config.")
    parser.add_argument(
        "--workspace-root",
        default="workspaces",
        help="Workspace root for family artifacts.",
    )
    parser.add_argument("--wave", type=int, default=None, help="Optional wave filter.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument(
        "--append-jsonl",
        default="",
        help="Optional JSONL path to append snapshots.",
    )
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    conf_path = Path(args.conf)
    workspace_root = Path(args.workspace_root)
    _defaults, assignments = _parse_swarm_conf(conf_path)

    rows: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for item in sorted(assignments, key=lambda a: (a.wave, a.pane, a.family)):
        if args.wave is not None and item.wave != args.wave:
            continue
        checkpoint_status, checkpoint, checkpoint_path = _read_checkpoint(workspace_root, item.family)
        checkpoint_last_update = str(checkpoint.get("last_update", "") or "")
        checkpoint_last_update_dt = _parse_dt(checkpoint_last_update)
        checkpoint_age_seconds = (
            int((now - checkpoint_last_update_dt).total_seconds())
            if checkpoint_last_update_dt is not None
            else None
        )
        artifacts = _family_artifacts(workspace_root, item.family)
        state = _family_state(
            checkpoint_status=checkpoint_status,
            strategy_count=int(artifacts["strategy_version_file_count"]),
            evidence_count=int(artifacts["evidence_file_count"]),
        )
        row = {
            "family": item.family,
            "wave": item.wave,
            "pane": item.pane,
            "backend": item.backend,
            "checkpoint_status": checkpoint_status,
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_last_update": checkpoint_last_update,
            "checkpoint_age_seconds": checkpoint_age_seconds,
            "checkpoint_iteration_count": int(checkpoint.get("iteration_count", 0) or 0),
            "checkpoint_last_strategy_version": int(
                checkpoint.get("last_strategy_version", 0) or 0
            ),
            "checkpoint_current_concept_id": str(
                checkpoint.get("current_concept_id") or checkpoint.get("last_concept_id") or ""
            ),
            "family_state": state,
        }
        row.update(artifacts)
        row["review_ready"] = bool(
            int(artifacts["strategy_version_file_count"]) > 0
            and int(artifacts["evidence_file_count"]) > 0
        )
        rows.append(row)

    summary = {
        "families_evaluated": len(rows),
        "running_count": sum(1 for r in rows if r["checkpoint_status"] == "running"),
        "completed_count": sum(1 for r in rows if r["checkpoint_status"] in {"completed", "locked"}),
        "missing_checkpoint_count": sum(1 for r in rows if r["checkpoint_status"] == "missing"),
        "with_strategy_count": sum(1 for r in rows if int(r["strategy_version_file_count"]) > 0),
        "with_evidence_count": sum(1 for r in rows if int(r["evidence_file_count"]) > 0),
        "with_judge_count": sum(1 for r in rows if int(r["judge_report_count"]) > 0),
        "review_ready_count": sum(1 for r in rows if bool(r["review_ready"])),
        "total_strategy_versions": sum(int(r["strategy_version_file_count"]) for r in rows),
        "total_evidence_files": sum(int(r["evidence_file_count"]) for r in rows),
        "total_evidence_records": sum(int(r["evidence_record_count"]) for r in rows),
        "total_judge_reports": sum(int(r["judge_report_count"]) for r in rows),
    }

    payload = {
        "schema_version": "swarm_artifact_manifest_v1",
        "generated_at": now.isoformat(),
        "config_path": str(conf_path),
        "workspace_root": str(workspace_root),
        "wave_filter": args.wave,
        "summary": summary,
        "rows": rows,
    }

    blob = _dumps(payload, indent=not args.compact)
    os.write(1, blob + b"\n")
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(blob + b"\n")
    if args.append_jsonl:
        append_path = Path(args.append_jsonl)
        append_path.parent.mkdir(parents=True, exist_ok=True)
        line = _dumps(payload, indent=False)
        with append_path.open("ab") as fh:
            fh.write(line + b"\n")


if __name__ == "__main__":
    main()
