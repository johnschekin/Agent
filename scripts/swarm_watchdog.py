#!/usr/bin/env python3
"""Swarm watchdog for stale/orphaned agent detection.

Builds on swarm assignment + checkpoint state to emit actionable alerts and
optionally mark stale/orphaned families as `stalled`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


_VERSION_FILE_PATTERN = re.compile(r"_v\d+\.json$")


def _workspace_stats(workspace_root: Path, family: str) -> dict[str, int]:
    root = workspace_root / family
    evidence = root / "evidence"
    strategies = root / "strategies"
    results = root / "results"
    evidence_count = len(list(evidence.glob("*.jsonl"))) if evidence.exists() else 0
    strategy_count = (
        len([fp for fp in strategies.glob("*.json") if _VERSION_FILE_PATTERN.search(fp.name)])
        if strategies.exists()
        else 0
    )
    result_count = len(list(results.glob("*.json"))) if results.exists() else 0
    return {
        "evidence_file_count": evidence_count,
        "strategy_version_file_count": strategy_count,
        "result_json_file_count": result_count,
    }


def _list_tmux_panes(session: str) -> tuple[bool, dict[int, dict[str, Any]], str]:
    try:
        probe = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, {}, "tmux_not_installed"
    if probe.returncode != 0:
        return False, {}, "tmux_session_missing"

    windows = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_index}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if windows.returncode != 0:
        return False, {}, "tmux_list_windows_failed"
    first_window = ""
    for line in windows.stdout.splitlines():
        line = line.strip()
        if line:
            first_window = line
            break
    if not first_window:
        return False, {}, "tmux_no_windows"

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
        return False, {}, "tmux_list_panes_failed"

    panes: dict[int, dict[str, Any]] = {}
    logical = 0
    for line in pane_out.stdout.splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = raw.split("|")
        if len(parts) != 4:
            continue
        pane_idx_raw, title, cmd, pid_raw = parts
        try:
            pane_idx = int(pane_idx_raw)
        except ValueError:
            pane_idx = -1
        try:
            pid = int(pid_raw)
        except ValueError:
            pid = 0
        panes[logical] = {
            "tmux_pane_index": pane_idx,
            "pane_title": title,
            "pane_command": cmd,
            "pane_pid": pid,
        }
        logical += 1
    return True, panes, ""


def _severity_rank(level: str) -> int:
    order = {"none": 0, "warning": 1, "critical": 2}
    return order.get(level, 0)


def _mark_stalled(checkpoint_path: Path, payload: dict[str, Any], reason: str) -> None:
    payload = dict(payload)
    payload["status"] = "stalled"
    payload["last_update"] = datetime.now(UTC).isoformat()
    payload["stalled_reason"] = reason
    payload["stalled_at"] = payload["last_update"]
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(payload, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Swarm watchdog for stale/orphaned agents.")
    parser.add_argument("--conf", default="swarm/swarm.conf", help="Path to swarm config.")
    parser.add_argument(
        "--workspace-root",
        default="workspaces",
        help="Workspace root for checkpoint lookups.",
    )
    parser.add_argument("--wave", type=int, default=None, help="Optional wave filter.")
    parser.add_argument(
        "--session",
        default="",
        help="Optional tmux session name (defaults to SESSION_NAME in config).",
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=90,
        help="Flag running families stale after this many minutes since last_update.",
    )
    parser.add_argument(
        "--bootstrap-grace-minutes",
        type=int,
        default=20,
        help=(
            "Flag running families as bootstrapping-stuck when they have zero "
            "strategy/evidence files and exceed this age."
        ),
    )
    parser.add_argument(
        "--check-pane-activity",
        action="store_true",
        help="Check tmux pane presence for running families and flag orphaned runs.",
    )
    parser.add_argument(
        "--mark-stalled",
        action="store_true",
        help="When alert condition matches, update checkpoint status to stalled.",
    )
    parser.add_argument(
        "--mark-on",
        choices=("warning", "critical"),
        default="critical",
        help="Minimum alert severity eligible for --mark-stalled.",
    )
    parser.add_argument(
        "--fail-on",
        choices=("none", "warning", "critical"),
        default="critical",
        help="Exit non-zero when alerts at/above this severity are present.",
    )
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument(
        "--append-jsonl",
        default="",
        help="Optional JSONL path to append watchdog snapshots.",
    )
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    conf_path = Path(args.conf)
    workspace_root = Path(args.workspace_root)
    defaults, assignments = _parse_swarm_conf(conf_path)
    session = args.session.strip() or defaults.get("SESSION_NAME", "")

    pane_supported = False
    pane_map: dict[int, dict[str, Any]] = {}
    pane_note = ""
    if args.check_pane_activity and session:
        pane_supported, pane_map, pane_note = _list_tmux_panes(session)
    elif args.check_pane_activity and not session:
        pane_note = "session_not_provided"

    now = datetime.now(UTC)
    stale_delta = timedelta(minutes=max(args.stale_minutes, 1))
    bootstrap_delta = timedelta(minutes=max(args.bootstrap_grace_minutes, 1))

    rows: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    mark_threshold = _severity_rank(args.mark_on)
    for item in sorted(assignments, key=lambda a: (a.wave, a.pane, a.family)):
        if args.wave is not None and item.wave != args.wave:
            continue
        status, checkpoint, checkpoint_path = _read_checkpoint(workspace_root, item.family)
        stats = _workspace_stats(workspace_root, item.family)
        last_update_raw = str(checkpoint.get("last_update", "") or "")
        last_update = _parse_dt(last_update_raw)
        age_seconds = int((now - last_update).total_seconds()) if last_update is not None else None
        running = status == "running"
        stale_running = bool(
            running and age_seconds is not None and age_seconds > int(stale_delta.total_seconds())
        )
        bootstrap_stuck = bool(
            running
            and age_seconds is not None
            and age_seconds > int(bootstrap_delta.total_seconds())
            and stats["strategy_version_file_count"] == 0
            and stats["evidence_file_count"] == 0
        )

        pane_active = None
        orphaned_running = False
        pane_meta: dict[str, Any] = {}
        if args.check_pane_activity and pane_supported:
            pane_meta = pane_map.get(item.pane, {})
            pane_active = bool(pane_meta)
            orphaned_running = bool(running and not pane_active)

        row = {
            "family": item.family,
            "wave": item.wave,
            "pane": item.pane,
            "backend": item.backend,
            "status": status,
            "checkpoint_path": str(checkpoint_path),
            "last_update": last_update_raw,
            "age_seconds": age_seconds,
            "stale_running": stale_running,
            "bootstrap_stuck": bootstrap_stuck,
            "orphaned_running": orphaned_running,
            "pane_active": pane_active,
            "pane_meta": pane_meta,
            "iteration_count": int(checkpoint.get("iteration_count", 0) or 0),
            "last_strategy_version": int(checkpoint.get("last_strategy_version", 0) or 0),
            "current_concept_id": str(checkpoint.get("current_concept_id", "") or ""),
            "evidence_file_count": stats["evidence_file_count"],
            "strategy_version_file_count": stats["strategy_version_file_count"],
            "result_json_file_count": stats["result_json_file_count"],
        }
        rows.append(row)

        if orphaned_running:
            alerts.append(
                {
                    "severity": "critical",
                    "family": item.family,
                    "wave": item.wave,
                    "type": "orphaned_running",
                    "message": "Checkpoint is running but assigned tmux pane is not active.",
                }
            )
        if stale_running:
            alerts.append(
                {
                    "severity": "warning",
                    "family": item.family,
                    "wave": item.wave,
                    "type": "stale_running",
                    "message": (
                        f"Checkpoint running without update for {age_seconds}s "
                        f"(threshold={int(stale_delta.total_seconds())}s)."
                    ),
                }
            )
        if bootstrap_stuck:
            alerts.append(
                {
                    "severity": "warning",
                    "family": item.family,
                    "wave": item.wave,
                    "type": "bootstrap_stuck",
                    "message": (
                        "Checkpoint running but no strategy/evidence files after "
                        f"{age_seconds}s."
                    ),
                }
            )

    if args.mark_stalled:
        indexed_rows = {str(row["family"]): row for row in rows}
        alert_by_family: dict[str, list[dict[str, Any]]] = {}
        for alert in alerts:
            alert_by_family.setdefault(str(alert["family"]), []).append(alert)

        for family, family_alerts in alert_by_family.items():
            max_alert_rank = max(_severity_rank(str(a["severity"])) for a in family_alerts)
            if max_alert_rank < mark_threshold:
                continue
            row = indexed_rows.get(family)
            if row is None:
                continue
            checkpoint_path = Path(str(row["checkpoint_path"]))
            status, checkpoint, _ = _read_checkpoint(workspace_root, family)
            if status != "running":
                continue
            reason = "; ".join(
                f"{a['type']}:{a['message']}" for a in family_alerts if isinstance(a, dict)
            )
            _mark_stalled(checkpoint_path, checkpoint, reason=reason)
            row["status"] = "stalled"
            row["stalled_by_watchdog"] = True
            alerts.append(
                {
                    "severity": "warning",
                    "family": family,
                    "wave": row["wave"],
                    "type": "status_updated",
                    "message": "Checkpoint status set to stalled by watchdog.",
                }
            )

    alert_counts = {"warning": 0, "critical": 0}
    for alert in alerts:
        sev = str(alert.get("severity", "")).lower()
        if sev in alert_counts:
            alert_counts[sev] += 1

    payload = {
        "schema_version": "swarm_watchdog_v1",
        "generated_at": now.isoformat(),
        "config_path": str(conf_path),
        "workspace_root": str(workspace_root),
        "wave_filter": args.wave,
        "session": session,
        "pane_check": {
            "requested": bool(args.check_pane_activity),
            "supported": bool(pane_supported),
            "note": pane_note,
        },
        "thresholds": {
            "stale_minutes": int(max(args.stale_minutes, 1)),
            "bootstrap_grace_minutes": int(max(args.bootstrap_grace_minutes, 1)),
            "mark_on": args.mark_on,
            "fail_on": args.fail_on,
        },
        "summary": {
            "families_evaluated": len(rows),
            "running_count": sum(1 for row in rows if row["status"] == "running"),
            "stalled_count": sum(1 for row in rows if row["status"] == "stalled"),
            "missing_checkpoint_count": sum(1 for row in rows if row["status"] == "missing"),
            "alert_count": len(alerts),
            "warning_count": alert_counts["warning"],
            "critical_count": alert_counts["critical"],
        },
        "alerts": alerts,
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

    fail_rank = _severity_rank(args.fail_on)
    max_rank = 0
    for sev in ("warning", "critical"):
        if alert_counts[sev] > 0:
            max_rank = max(max_rank, _severity_rank(sev))
    if fail_rank > 0 and max_rank >= fail_rank:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
