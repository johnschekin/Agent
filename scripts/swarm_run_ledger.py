#!/usr/bin/env python3
"""Emit a machine-readable swarm run ledger snapshot.

The ledger is intended for Gate-4/Gate-5 rollout governance. It reads swarm
assignments + per-family checkpoint state and summarizes current run health.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import orjson

    def dump_json(obj: Any, *, indent: bool) -> bytes:
        option = orjson.OPT_INDENT_2 if indent else 0
        return orjson.dumps(obj, option=option)
except ImportError:

    def dump_json(obj: Any, *, indent: bool) -> bytes:
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


def _parse_dt(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _read_checkpoint(workspace_root: Path, family: str) -> tuple[str, dict[str, Any], str]:
    fp = workspace_root / family / "checkpoint.json"
    if not fp.exists():
        return "missing", {}, ""
    try:
        payload = json.loads(fp.read_text())
    except json.JSONDecodeError:
        return "invalid", {}, str(fp)
    if not isinstance(payload, dict):
        return "invalid", {}, str(fp)
    status = str(payload.get("status", "")).strip().lower() or "initialized"
    return status, payload, str(fp)


_VERSION_FILE_PATTERN = re.compile(r"_v\d+\.json$")


def _latest_path(files: list[Path]) -> Path | None:
    if not files:
        return None
    return max(files, key=lambda fp: fp.stat().st_mtime)


def _collect_workspace_stats(workspace_root: Path, family: str) -> dict[str, Any]:
    root = workspace_root / family
    evidence_dir = root / "evidence"
    strategies_dir = root / "strategies"
    results_dir = root / "results"

    evidence_files = sorted(evidence_dir.glob("*.jsonl")) if evidence_dir.exists() else []
    version_files = (
        sorted(
            fp for fp in strategies_dir.glob("*.json") if _VERSION_FILE_PATTERN.search(fp.name)
        )
        if strategies_dir.exists()
        else []
    )
    result_json = sorted(results_dir.glob("*.json")) if results_dir.exists() else []

    latest_evidence = _latest_path(evidence_files)
    latest_strategy = _latest_path(version_files)
    latest_result = _latest_path(result_json)

    return {
        "evidence_file_count": len(evidence_files),
        "strategy_version_file_count": len(version_files),
        "result_json_file_count": len(result_json),
        "latest_evidence_file": str(latest_evidence) if latest_evidence else "",
        "latest_strategy_file": str(latest_strategy) if latest_strategy else "",
        "latest_result_file": str(latest_result) if latest_result else "",
    }


def _list_tmux_panes(session: str) -> dict[int, dict[str, Any]]:
    try:
        probe = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {}
    if probe.returncode != 0:
        return {}

    windows = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_index}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if windows.returncode != 0:
        return {}
    first_window = ""
    for line in windows.stdout.splitlines():
        candidate = line.strip()
        if candidate:
            first_window = candidate
            break
    if not first_window:
        return {}

    pane_out = subprocess.run(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session}:{first_window}",
            "-F",
            "#{pane_index}|#{pane_title}|#{pane_current_command}|#{pane_pid}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if pane_out.returncode != 0:
        return {}

    panes: dict[int, dict[str, Any]] = {}
    logical = 0
    for line in pane_out.stdout.splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = raw.split("|")
        if len(parts) != 4:
            continue
        pane_index_raw, title, cmd, pid_raw = parts
        try:
            pane_index = int(pane_index_raw)
        except ValueError:
            pane_index = -1
        try:
            pid = int(pid_raw)
        except ValueError:
            pid = 0
        panes[logical] = {
            "tmux_pane_index": pane_index,
            "pane_title": title,
            "pane_command": cmd,
            "pane_pid": pid,
        }
        logical += 1
    return panes


def _build_rows(
    assignments: list[Assignment],
    *,
    workspace_root: Path,
    wave: int | None,
    stale_delta: timedelta,
    now_utc: datetime,
    pane_map: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in assignments:
        if wave is not None and item.wave != wave:
            continue
        checkpoint_status, checkpoint, checkpoint_path = _read_checkpoint(workspace_root, item.family)
        last_update_raw = str(checkpoint.get("last_update", "") or "")
        last_update_dt = _parse_dt(last_update_raw)
        age_seconds = (
            int((now_utc - last_update_dt).total_seconds()) if last_update_dt is not None else None
        )
        is_stale = (
            checkpoint_status == "running"
            and age_seconds is not None
            and age_seconds > int(stale_delta.total_seconds())
        )
        workspace_stats = _collect_workspace_stats(workspace_root, item.family)
        pane_meta = pane_map.get(item.pane, {})
        row = {
            "family": item.family,
            "pane": item.pane,
            "wave": item.wave,
            "backend": item.backend,
            "whitelist": item.whitelist,
            "depends_on": list(item.dependencies),
            "checkpoint_status": checkpoint_status,
            "checkpoint_path": checkpoint_path,
            "checkpoint_last_update": last_update_raw,
            "checkpoint_age_seconds": age_seconds,
            "checkpoint_is_stale_running": is_stale,
            "checkpoint_iteration_count": int(checkpoint.get("iteration_count", 0) or 0),
            "checkpoint_last_strategy_version": int(
                checkpoint.get("last_strategy_version", 0) or 0
            ),
            "checkpoint_current_concept_id": str(
                checkpoint.get("current_concept_id") or checkpoint.get("last_concept_id") or ""
            ),
            "checkpoint_last_coverage_hit_rate": checkpoint.get("last_coverage_hit_rate"),
            "pane_active": bool(pane_meta),
            "pane_meta": pane_meta,
        }
        row.update(workspace_stats)
        rows.append(row)
    rows.sort(key=lambda r: (int(r["wave"]), int(r["pane"]), str(r["family"])))
    return rows


def _summary(rows: list[dict[str, Any]], stale_minutes: int) -> dict[str, Any]:
    status_counter = Counter(str(r["checkpoint_status"]) for r in rows)
    wave_counter = Counter(int(r["wave"]) for r in rows)
    stale_count = sum(1 for r in rows if r["checkpoint_is_stale_running"])
    with_evidence = sum(1 for r in rows if int(r["evidence_file_count"]) > 0)
    with_strategy_versions = sum(1 for r in rows if int(r["strategy_version_file_count"]) > 0)
    completed_like = sum(
        1 for r in rows if str(r["checkpoint_status"]) in {"completed", "locked"}
    )
    running_like = sum(1 for r in rows if str(r["checkpoint_status"]) == "running")
    return {
        "assignments": len(rows),
        "waves": {str(k): v for k, v in sorted(wave_counter.items())},
        "checkpoint_status_counts": dict(sorted(status_counter.items())),
        "stale_running_count": stale_count,
        "stale_threshold_minutes": stale_minutes,
        "completed_like_count": completed_like,
        "running_count": running_like,
        "with_evidence_count": with_evidence,
        "with_strategy_version_count": with_strategy_versions,
        "missing_checkpoint_count": status_counter.get("missing", 0),
        "invalid_checkpoint_count": status_counter.get("invalid", 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate swarm run ledger snapshot.")
    parser.add_argument("--conf", default="swarm/swarm.conf", help="Path to swarm config.")
    parser.add_argument(
        "--workspace-root",
        default="workspaces",
        help="Path to workspace root for checkpoint/evidence state.",
    )
    parser.add_argument("--wave", type=int, default=None, help="Optional wave filter.")
    parser.add_argument(
        "--session",
        default="",
        help=(
            "Optional tmux session for pane metadata. "
            "Defaults to SESSION_NAME in swarm config when available."
        ),
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=120,
        help="Mark running checkpoints stale when last_update exceeds this age.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON output path. Always prints JSON to stdout.",
    )
    parser.add_argument(
        "--append-jsonl",
        default="",
        help="Optional JSONL path to append one ledger snapshot record per run.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON (single line).",
    )
    args = parser.parse_args()

    conf_path = Path(args.conf)
    workspace_root = Path(args.workspace_root)
    defaults, assignments = _parse_swarm_conf(conf_path)
    session = args.session.strip() or defaults.get("SESSION_NAME", "")

    now_utc = datetime.now(UTC)
    stale_delta = timedelta(minutes=max(args.stale_minutes, 1))
    pane_map = _list_tmux_panes(session) if session else {}
    rows = _build_rows(
        assignments,
        workspace_root=workspace_root,
        wave=args.wave,
        stale_delta=stale_delta,
        now_utc=now_utc,
        pane_map=pane_map,
    )

    payload = {
        "schema_version": "swarm_run_ledger_v1",
        "generated_at": now_utc.isoformat(),
        "config_path": str(conf_path),
        "workspace_root": str(workspace_root),
        "wave_filter": args.wave,
        "session": session,
        "session_detected": bool(pane_map),
        "summary": _summary(rows, stale_minutes=max(args.stale_minutes, 1)),
        "rows": rows,
    }

    blob = dump_json(payload, indent=not args.compact)
    os.write(1, blob + b"\n")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(blob + b"\n")

    if args.append_jsonl:
        log_path = Path(args.append_jsonl)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        line = dump_json(payload, indent=False)
        with log_path.open("ab") as fh:
            fh.write(line)
            fh.write(b"\n")


if __name__ == "__main__":
    main()
