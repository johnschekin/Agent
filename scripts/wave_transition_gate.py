#!/usr/bin/env python3
"""Evaluate whether a target wave is eligible to dispatch.

This gate enforces prior-wave completion before higher-wave rollout,
with optional explicit waivers.
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

    def _dumps(obj: Any, *, indent: bool) -> bytes:
        option = orjson.OPT_INDENT_2 if indent else 0
        return orjson.dumps(obj, option=option)

    def _loads(path: Path) -> Any:
        return orjson.loads(path.read_bytes())
except ImportError:

    def _dumps(obj: Any, *, indent: bool) -> bytes:
        text = json.dumps(obj, indent=2 if indent else None, default=str)
        return text.encode("utf-8")

    def _loads(path: Path) -> Any:
        with open(path) as f:
            return json.load(f)


@dataclass(frozen=True, slots=True)
class Assignment:
    family: str
    pane: int
    wave: int
    backend: str
    whitelist: str
    dependencies: tuple[str, ...]


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
        payload = _loads(fp)
    except Exception:
        return "invalid", {}
    if not isinstance(payload, dict):
        return "invalid", {}
    status = str(payload.get("status", "")).strip().lower() or "initialized"
    return status, payload


def _load_waivers(path: Path | None) -> tuple[dict[str, str], dict[str, Any]]:
    if path is None:
        return {}, {}
    if not path.exists():
        return {}, {"error": f"waiver file not found: {path}"}
    try:
        payload = _loads(path)
    except Exception as exc:
        return {}, {"error": f"failed to parse waiver file: {exc}"}
    if not isinstance(payload, dict):
        return {}, {"error": "waiver file must be a JSON object"}

    waivers: dict[str, str] = {}

    def add_family(family: str, reason: str) -> None:
        fam = family.strip()
        if not fam:
            return
        waivers[fam] = reason.strip() or "waived"

    raw_list = payload.get("waived_families")
    if isinstance(raw_list, list):
        for item in raw_list:
            if isinstance(item, str):
                add_family(item, "waiver_file")
            elif isinstance(item, dict):
                add_family(
                    str(item.get("family", "")),
                    str(item.get("reason", "") or "waiver_file"),
                )

    raw_map = payload.get("waivers")
    if isinstance(raw_map, dict):
        for key, val in raw_map.items():
            add_family(str(key), str(val))

    return waivers, payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate wave dispatch on prior-wave completion.")
    parser.add_argument("--conf", default="swarm/swarm.conf", help="Path to swarm config.")
    parser.add_argument(
        "--workspace-root",
        default="workspaces",
        help="Workspace root for checkpoint lookups.",
    )
    parser.add_argument(
        "--target-wave",
        type=int,
        required=True,
        help="Wave number to evaluate for dispatch eligibility.",
    )
    parser.add_argument(
        "--scope",
        choices=("previous", "all-prior"),
        default="previous",
        help="Prerequisite scope: previous wave only or all lower waves.",
    )
    parser.add_argument(
        "--completed-statuses",
        default="completed,locked",
        help="Comma-separated statuses treated as complete.",
    )
    parser.add_argument(
        "--waiver-file",
        default="",
        help="Optional waiver JSON file allowing specific prerequisite families.",
    )
    parser.add_argument(
        "--waive-family",
        action="append",
        default=[],
        help="Inline waiver family id. Can be provided multiple times.",
    )
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    conf_path = Path(args.conf)
    workspace_root = Path(args.workspace_root)
    assignments = _parse_swarm_conf(conf_path)

    completed = {v.strip().lower() for v in args.completed_statuses.split(",") if v.strip()}
    waiver_path = Path(args.waiver_file) if args.waiver_file else None
    waivers, waiver_meta = _load_waivers(waiver_path)
    for fam in args.waive_family:
        key = str(fam).strip()
        if key:
            waivers[key] = "inline"

    prerequisite_waves: set[int] = set()
    if args.target_wave > 1:
        if args.scope == "previous":
            prerequisite_waves = {args.target_wave - 1}
        else:
            prerequisite_waves = set(range(1, args.target_wave))

    prereq_assignments = [a for a in assignments if a.wave in prerequisite_waves]
    blocked_rows: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for item in sorted(prereq_assignments, key=lambda a: (a.wave, a.pane, a.family)):
        status, checkpoint_payload = _checkpoint_status(workspace_root, item.family)
        is_complete = status in completed
        waived_reason = waivers.get(item.family, "")
        is_waived = bool(waived_reason)
        blocked = not is_complete and not is_waived
        row = {
            "family": item.family,
            "wave": item.wave,
            "pane": item.pane,
            "status": status,
            "is_complete": is_complete,
            "is_waived": is_waived,
            "waiver_reason": waived_reason,
            "blocked": blocked,
            "last_update": str(checkpoint_payload.get("last_update", "") or ""),
            "iteration_count": int(checkpoint_payload.get("iteration_count", 0) or 0),
            "last_strategy_version": int(checkpoint_payload.get("last_strategy_version", 0) or 0),
        }
        rows.append(row)
        if blocked:
            blocked_rows.append(row)

    allowed = len(blocked_rows) == 0
    if args.target_wave <= 1:
        reason = "target wave is 1; no prerequisite waves"
    elif not prereq_assignments:
        reason = "no prerequisite assignments found in config"
    elif allowed:
        reason = "all prerequisite families complete or waived"
    else:
        reason = f"{len(blocked_rows)} prerequisite families are incomplete and not waived"

    payload = {
        "schema_version": "wave_transition_gate_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "config_path": str(conf_path),
        "workspace_root": str(workspace_root),
        "target_wave": args.target_wave,
        "scope": args.scope,
        "completed_statuses": sorted(completed),
        "waiver_file": str(waiver_path) if waiver_path else "",
        "summary": {
            "prerequisite_waves": sorted(prerequisite_waves),
            "prerequisite_assignments": len(prereq_assignments),
            "blocked_count": len(blocked_rows),
            "waived_count": sum(1 for row in rows if row["is_waived"]),
            "complete_count": sum(1 for row in rows if row["is_complete"]),
        },
        "decision": {
            "allowed": allowed,
            "reason": reason,
        },
        "waiver_meta": waiver_meta,
        "rows": rows,
        "blocked": blocked_rows,
    }

    blob = _dumps(payload, indent=not args.compact)
    import os

    os.write(1, blob + b"\n")
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(blob + b"\n")

    if not allowed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
