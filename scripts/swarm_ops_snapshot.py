#!/usr/bin/env python3
"""Generate consolidated swarm operations snapshot artifacts.

Runs the existing operational tools and emits one merged JSON report:
- swarm_run_ledger
- swarm_watchdog
- swarm_artifact_manifest
- optional wave_transition_gate
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import orjson

    def _loads(raw: bytes) -> Any:
        return orjson.loads(raw)

    def _dumps(obj: Any, *, indent: bool) -> bytes:
        option = orjson.OPT_INDENT_2 if indent else 0
        return orjson.dumps(obj, option=option)
except ImportError:

    def _loads(raw: bytes) -> Any:
        return json.loads(raw.decode("utf-8"))

    def _dumps(obj: Any, *, indent: bool) -> bytes:
        text = json.dumps(obj, indent=2 if indent else None, default=str)
        return text.encode("utf-8")


def _run_json_tool(cmd: list[str]) -> tuple[int, dict[str, Any], str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=False,
        check=False,
    )
    payload: dict[str, Any] = {}
    parse_error = ""
    if proc.stdout:
        try:
            loaded = _loads(proc.stdout)
            if isinstance(loaded, dict):
                payload = loaded
            else:
                parse_error = "stdout JSON payload is not an object"
        except Exception as exc:
            parse_error = str(exc)
    elif proc.stderr:
        parse_error = proc.stderr.decode("utf-8", errors="replace").strip()
    return proc.returncode, payload, parse_error


def _artifact_path(base_dir: Path, stem: str, wave: int | None, generated_at: datetime) -> Path:
    suffix = generated_at.strftime("%Y-%m-%d")
    if wave is not None:
        return base_dir / f"wave{wave}_{stem}_{suffix}.json"
    return base_dir / f"{stem}_{suffix}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidated swarm ops snapshot.")
    parser.add_argument("--conf", default="swarm/swarm.conf", help="Path to swarm config.")
    parser.add_argument(
        "--workspace-root",
        default="workspaces",
        help="Workspace root path.",
    )
    parser.add_argument("--session", default="", help="Tmux session name (optional).")
    parser.add_argument("--wave", type=int, default=None, help="Optional current-wave focus.")
    parser.add_argument(
        "--next-wave",
        type=int,
        default=None,
        help="Optional next-wave number for transition gate evaluation.",
    )
    parser.add_argument(
        "--transition-scope",
        choices=("previous", "all-prior"),
        default="previous",
        help="Transition gate prerequisite scope.",
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=90,
        help="Watchdog stale threshold.",
    )
    parser.add_argument(
        "--bootstrap-grace-minutes",
        type=int,
        default=20,
        help="Watchdog bootstrap grace threshold.",
    )
    parser.add_argument(
        "--watchdog-check-pane-activity",
        action="store_true",
        help="Enable watchdog pane activity checks.",
    )
    parser.add_argument(
        "--plans-dir",
        default="plans",
        help="Directory where sub-artifacts are written by this snapshot run.",
    )
    parser.add_argument("--output", default="", help="Optional consolidated output path.")
    parser.add_argument(
        "--append-jsonl",
        default="",
        help="Optional consolidated JSONL history path.",
    )
    parser.add_argument(
        "--require-next-wave-allowed",
        action="store_true",
        help="Exit non-zero when --next-wave is set and transition gate is blocked.",
    )
    parser.add_argument(
        "--require-no-critical-alerts",
        action="store_true",
        help="Exit non-zero when watchdog reports critical alerts.",
    )
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    conf_path = Path(args.conf)
    if not conf_path.is_absolute():
        conf_path = (repo_root / conf_path).resolve()
    workspace_root = Path(args.workspace_root)
    if not workspace_root.is_absolute():
        workspace_root = (repo_root / workspace_root).resolve()
    plans_dir = Path(args.plans_dir)
    if not plans_dir.is_absolute():
        plans_dir = (repo_root / plans_dir).resolve()
    plans_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(UTC)
    py = sys.executable

    ledger_out = _artifact_path(
        plans_dir,
        "swarm_ledger",
        args.wave,
        generated_at,
    )
    watchdog_out = _artifact_path(
        plans_dir,
        "watchdog",
        args.wave,
        generated_at,
    )
    manifest_out = _artifact_path(
        plans_dir,
        "artifact_manifest",
        args.wave,
        generated_at,
    )

    ledger_cmd = [
        py,
        str(repo_root / "scripts" / "swarm_run_ledger.py"),
        "--conf",
        str(conf_path),
        "--workspace-root",
        str(workspace_root),
        "--output",
        str(ledger_out),
        "--compact",
    ]
    if args.wave is not None:
        ledger_cmd.extend(["--wave", str(args.wave)])
    if args.session:
        ledger_cmd.extend(["--session", args.session])

    watchdog_cmd = [
        py,
        str(repo_root / "scripts" / "swarm_watchdog.py"),
        "--conf",
        str(conf_path),
        "--workspace-root",
        str(workspace_root),
        "--stale-minutes",
        str(max(args.stale_minutes, 1)),
        "--bootstrap-grace-minutes",
        str(max(args.bootstrap_grace_minutes, 1)),
        "--fail-on",
        "none",
        "--output",
        str(watchdog_out),
        "--compact",
    ]
    if args.wave is not None:
        watchdog_cmd.extend(["--wave", str(args.wave)])
    if args.watchdog_check_pane_activity:
        watchdog_cmd.append("--check-pane-activity")
    if args.session:
        watchdog_cmd.extend(["--session", args.session])

    manifest_cmd = [
        py,
        str(repo_root / "scripts" / "swarm_artifact_manifest.py"),
        "--conf",
        str(conf_path),
        "--workspace-root",
        str(workspace_root),
        "--output",
        str(manifest_out),
        "--compact",
    ]
    if args.wave is not None:
        manifest_cmd.extend(["--wave", str(args.wave)])

    ledger_rc, ledger_payload, ledger_err = _run_json_tool(ledger_cmd)
    watchdog_rc, watchdog_payload, watchdog_err = _run_json_tool(watchdog_cmd)
    manifest_rc, manifest_payload, manifest_err = _run_json_tool(manifest_cmd)

    transition_payload: dict[str, Any] = {}
    transition_rc = 0
    transition_err = ""
    transition_out_path = ""
    if args.next_wave is not None:
        transition_out = _artifact_path(
            plans_dir,
            f"transition_gate_wave{args.next_wave}",
            None,
            generated_at,
        )
        transition_cmd = [
            py,
            str(repo_root / "scripts" / "wave_transition_gate.py"),
            "--conf",
            str(conf_path),
            "--workspace-root",
            str(workspace_root),
            "--target-wave",
            str(args.next_wave),
            "--scope",
            args.transition_scope,
            "--output",
            str(transition_out),
            "--compact",
        ]
        transition_rc, transition_payload, transition_err = _run_json_tool(transition_cmd)
        transition_out_path = str(transition_out)

    critical_alerts = int(watchdog_payload.get("summary", {}).get("critical_count", 0) or 0)
    transition_allowed = bool(transition_payload.get("decision", {}).get("allowed", True))

    go_no_go = {
        "no_critical_alerts": critical_alerts == 0,
        "next_wave_allowed": transition_allowed if args.next_wave is not None else None,
    }
    blocking_reasons: list[str] = []
    if args.require_no_critical_alerts and critical_alerts > 0:
        blocking_reasons.append(f"critical watchdog alerts present ({critical_alerts})")
    if args.require_next_wave_allowed and args.next_wave is not None and not transition_allowed:
        reason = str(transition_payload.get("decision", {}).get("reason", "")).strip()
        blocking_reasons.append(reason or f"next wave {args.next_wave} blocked")

    payload = {
        "schema_version": "swarm_ops_snapshot_v1",
        "generated_at": generated_at.isoformat(),
        "config_path": str(conf_path),
        "workspace_root": str(workspace_root),
        "wave_filter": args.wave,
        "session": args.session,
        "next_wave": args.next_wave,
        "transition_scope": args.transition_scope,
        "artifacts": {
            "ledger": str(ledger_out),
            "watchdog": str(watchdog_out),
            "artifact_manifest": str(manifest_out),
            "transition_gate": transition_out_path,
        },
        "subprocess": {
            "ledger": {"returncode": ledger_rc, "error": ledger_err},
            "watchdog": {"returncode": watchdog_rc, "error": watchdog_err},
            "artifact_manifest": {"returncode": manifest_rc, "error": manifest_err},
            "transition_gate": {"returncode": transition_rc, "error": transition_err},
        },
        "summary": {
            "ledger": ledger_payload.get("summary", {}),
            "watchdog": watchdog_payload.get("summary", {}),
            "artifact_manifest": manifest_payload.get("summary", {}),
            "transition_gate": transition_payload.get("summary", {}),
        },
        "decision": {
            "go_no_go": go_no_go,
            "blocking_reasons": blocking_reasons,
            "allowed": len(blocking_reasons) == 0,
        },
    }

    blob = _dumps(payload, indent=not args.compact)
    os.write(1, blob + b"\n")
    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = (repo_root / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(blob + b"\n")
    if args.append_jsonl:
        append_path = Path(args.append_jsonl)
        if not append_path.is_absolute():
            append_path = (repo_root / append_path).resolve()
        append_path.parent.mkdir(parents=True, exist_ok=True)
        line = _dumps(payload, indent=False)
        with append_path.open("ab") as fh:
            fh.write(line + b"\n")

    if blocking_reasons:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
