#!/usr/bin/env python3
"""Dependency-aware swarm family scheduling helper.

Reads swarm assignments and workspace checkpoints, then emits dispatchable
families for a requested wave/mode.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import orjson

    def dump_json(obj: Any) -> None:
        import sys

        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: Any) -> None:
        print(json.dumps(obj, indent=2, default=str))


@dataclass(frozen=True, slots=True)
class Assignment:
    family: str
    pane: int
    wave: int
    backend: str
    whitelist: str
    dependencies: tuple[str, ...] = ()


def _parse_swarm_conf(conf_path: Path) -> list[Assignment]:
    if not conf_path.exists():
        return []
    assignments: list[Assignment] = []
    for line in conf_path.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" in raw or "|" not in raw:
            continue
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
    return assignments


def _checkpoint_status(workspace_root: Path, family: str) -> tuple[str, dict[str, Any]]:
    fp = workspace_root / family / "checkpoint.json"
    if not fp.exists():
        return "missing", {}
    try:
        payload = json.loads(fp.read_text())
    except json.JSONDecodeError:
        return "invalid", {}
    if not isinstance(payload, dict):
        return "invalid", {}
    status = str(payload.get("status", "")).strip().lower() or "initialized"
    return status, payload


def _dependencies_ready(
    assignment: Assignment,
    status_by_family: dict[str, str],
) -> tuple[bool, list[dict[str, str]]]:
    blockers: list[dict[str, str]] = []
    for dep in assignment.dependencies:
        dep_status = status_by_family.get(dep, "missing")
        if dep_status not in {"completed", "locked"}:
            blockers.append({"dependency": dep, "status": dep_status})
    return len(blockers) == 0, blockers


def main() -> None:
    parser = argparse.ArgumentParser(description="Dependency-aware swarm family scheduler.")
    parser.add_argument(
        "--conf",
        default="swarm/swarm.conf",
        help="Path to swarm.conf assignment file.",
    )
    parser.add_argument(
        "--workspace-root",
        default="workspaces",
        help="Path to workspaces root for checkpoint status lookups.",
    )
    parser.add_argument("--wave", type=int, default=None, help="Optional wave filter.")
    parser.add_argument(
        "--mode",
        choices=("ready", "failed", "all"),
        default="ready",
        help="Queue mode: ready (default), failed-only, or all in-wave.",
    )
    parser.add_argument(
        "--failed-statuses",
        default="failed,error,stalled",
        help="Comma-separated statuses considered failed in --mode failed.",
    )
    parser.add_argument(
        "--allow-running",
        action="store_true",
        help="Allow scheduling families with status=running in ready mode.",
    )
    parser.add_argument(
        "--allow-completed",
        action="store_true",
        help="Allow scheduling families with status=completed/locked in ready mode.",
    )
    parser.add_argument(
        "--families-out",
        default=None,
        help="Optional newline-delimited output file of scheduled families.",
    )
    args = parser.parse_args()

    conf_path = Path(args.conf)
    workspace_root = Path(args.workspace_root)
    assignments = _parse_swarm_conf(conf_path)

    failed_statuses = {v.strip().lower() for v in args.failed_statuses.split(",") if v.strip()}
    status_by_family: dict[str, str] = {}
    checkpoint_payloads: dict[str, dict[str, Any]] = {}
    for a in assignments:
        status, payload = _checkpoint_status(workspace_root, a.family)
        status_by_family[a.family] = status
        checkpoint_payloads[a.family] = payload

    total = 0
    selected: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for a in assignments:
        if args.wave is not None and a.wave != args.wave:
            continue
        total += 1
        status = status_by_family.get(a.family, "missing")
        dep_ready, dep_blockers = _dependencies_ready(a, status_by_family)

        if args.mode == "failed":
            if status not in failed_statuses:
                skipped.append({"family": a.family, "reason": f"status={status}"})
                continue
            selected.append(
                {
                    "family": a.family,
                    "pane": a.pane,
                    "wave": a.wave,
                    "backend": a.backend,
                    "status": status,
                    "dependencies": list(a.dependencies),
                    "dependency_ready": dep_ready,
                    "dependency_blockers": dep_blockers,
                }
            )
            continue

        if args.mode == "all":
            selected.append(
                {
                    "family": a.family,
                    "pane": a.pane,
                    "wave": a.wave,
                    "backend": a.backend,
                    "status": status,
                    "dependencies": list(a.dependencies),
                    "dependency_ready": dep_ready,
                    "dependency_blockers": dep_blockers,
                }
            )
            continue

        # mode=ready
        if status == "running" and not args.allow_running:
            skipped.append({"family": a.family, "reason": "already_running"})
            continue
        if status in {"completed", "locked"} and not args.allow_completed:
            skipped.append({"family": a.family, "reason": f"status={status}"})
            continue
        if not dep_ready:
            blocked.append(
                {
                    "family": a.family,
                    "status": status,
                    "dependencies": list(a.dependencies),
                    "dependency_blockers": dep_blockers,
                }
            )
            continue
        selected.append(
            {
                "family": a.family,
                "pane": a.pane,
                "wave": a.wave,
                "backend": a.backend,
                "status": status,
                "dependencies": list(a.dependencies),
                "dependency_ready": dep_ready,
                "dependency_blockers": [],
            }
        )

    families_out_path = Path(args.families_out) if args.families_out else None
    if families_out_path is not None:
        families_out_path.parent.mkdir(parents=True, exist_ok=True)
        families_out_path.write_text(
            "".join(f"{row['family']}\n" for row in selected)
        )

    payload = {
        "schema_version": "wave_scheduler_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "config_path": str(conf_path),
        "workspace_root": str(workspace_root),
        "mode": args.mode,
        "wave": args.wave,
        "summary": {
            "considered_assignments": total,
            "selected_count": len(selected),
            "blocked_count": len(blocked),
            "skipped_count": len(skipped),
        },
        "selected": selected,
        "blocked": blocked,
        "skipped": skipped,
        "checkpoint_status_by_family": status_by_family,
        "families_out": str(families_out_path) if families_out_path else "",
        "failed_statuses": sorted(failed_statuses),
    }
    dump_json(payload)


if __name__ == "__main__":
    main()
