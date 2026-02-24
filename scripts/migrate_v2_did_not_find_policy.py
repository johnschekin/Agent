#!/usr/bin/env python3
"""Migrate v2 strategy JSON files to include starter did_not_find_policy.

Usage:
    python3 scripts/migrate_v2_did_not_find_policy.py \
      --path workspaces/indebtedness/strategies \
      --recursive \
      --dry-run

By default, only missing starter keys are added for v2 strategies:
  - min_coverage
  - max_near_miss_rate
  - max_near_miss_count

Use --force to overwrite those starter keys even when already present.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import orjson

    def load_json(path: Path) -> object:
        return orjson.loads(path.read_bytes())

    def write_json(path: Path, obj: object) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def load_json(path: Path) -> object:
        with open(path) as f:
            return json.load(f)

    def write_json(path: Path, obj: object) -> None:
        with open(path, "w") as f:
            json.dump(obj, f, indent=2, default=str)

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_starter_policy(
    *,
    min_coverage: float,
    max_near_miss_rate: float,
    max_near_miss_count: int,
    near_miss_cutoff: float | None = None,
) -> dict[str, Any]:
    starter: dict[str, Any] = {
        "min_coverage": float(min_coverage),
        "max_near_miss_rate": float(max_near_miss_rate),
        "max_near_miss_count": int(max_near_miss_count),
    }
    if near_miss_cutoff is not None:
        starter["near_miss_cutoff"] = float(near_miss_cutoff)
    return starter


def collect_strategy_files(
    root: Path,
    *,
    recursive: bool,
    pattern: str,
) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    if recursive:
        return sorted(p for p in root.rglob(pattern) if p.is_file())
    return sorted(p for p in root.glob(pattern) if p.is_file())


def migrate_strategy_payload(
    payload: object,
    *,
    starter_policy: dict[str, Any],
    force: bool,
) -> tuple[object, bool, str]:
    """Return (updated_payload, changed, status_code)."""
    if not isinstance(payload, dict):
        return payload, False, "skip_non_object"

    if payload.get("acceptance_policy_version", "v1") != "v2":
        return payload, False, "skip_not_v2"

    current_policy = payload.get("did_not_find_policy")
    changed = False

    if not isinstance(current_policy, dict):
        current_policy = {}
        changed = True

    for key, value in starter_policy.items():
        if force:
            if current_policy.get(key) != value:
                current_policy[key] = value
                changed = True
        else:
            if key not in current_policy:
                current_policy[key] = value
                changed = True

    payload["did_not_find_policy"] = current_policy
    if changed:
        return payload, True, "updated"
    return payload, False, "skip_already_configured"


def migrate_file(
    path: Path,
    *,
    starter_policy: dict[str, Any],
    force: bool,
    dry_run: bool,
    backup: bool,
) -> dict[str, Any]:
    try:
        payload = load_json(path)
    except Exception as exc:
        return {"path": str(path), "status": "error_parse", "error": str(exc)}

    updated, changed, status = migrate_strategy_payload(
        payload,
        starter_policy=starter_policy,
        force=force,
    )

    result = {
        "path": str(path),
        "status": status,
        "changed": changed,
    }
    if changed and not dry_run:
        if backup:
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)
            result["backup"] = str(backup_path)
        write_json(path, updated)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add starter did_not_find_policy to v2 strategy JSON files."
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Strategy JSON file or directory containing strategy JSON files.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan subdirectories (when --path is a directory).",
    )
    parser.add_argument(
        "--pattern",
        default="*.json",
        help='Filename pattern for directory scans (default: "*.json").',
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite starter keys even when already present.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report updates without writing files.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Write .bak backup before modifying each file.",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.90,
        help="Starter did_not_find_policy.min_coverage (default: 0.90).",
    )
    parser.add_argument(
        "--max-near-miss-rate",
        type=float,
        default=0.15,
        help="Starter did_not_find_policy.max_near_miss_rate (default: 0.15).",
    )
    parser.add_argument(
        "--max-near-miss-count",
        type=int,
        default=10,
        help="Starter did_not_find_policy.max_near_miss_count (default: 10).",
    )
    parser.add_argument(
        "--near-miss-cutoff",
        type=float,
        default=None,
        help="Optional starter did_not_find_policy.near_miss_cutoff.",
    )
    args = parser.parse_args()

    root = Path(args.path)
    files = collect_strategy_files(
        root,
        recursive=args.recursive,
        pattern=args.pattern,
    )
    if not files:
        log(f"No files found for path={root} pattern={args.pattern}")
        dump_json(
            {
                "status": "ok",
                "scanned": 0,
                "updated": 0,
                "dry_run": bool(args.dry_run),
                "results": [],
            }
        )
        return

    starter_policy = build_starter_policy(
        min_coverage=args.min_coverage,
        max_near_miss_rate=args.max_near_miss_rate,
        max_near_miss_count=args.max_near_miss_count,
        near_miss_cutoff=args.near_miss_cutoff,
    )

    results: list[dict[str, Any]] = []
    counts = {
        "updated": 0,
        "skip_not_v2": 0,
        "skip_already_configured": 0,
        "skip_non_object": 0,
        "error_parse": 0,
    }

    for path in files:
        res = migrate_file(
            path,
            starter_policy=starter_policy,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
            backup=bool(args.backup),
        )
        results.append(res)
        status = str(res.get("status", "unknown"))
        if status in counts:
            counts[status] += 1
        elif res.get("changed"):
            counts["updated"] += 1

    dump_json(
        {
            "status": "ok",
            "scanned": len(files),
            "updated": counts["updated"],
            "dry_run": bool(args.dry_run),
            "starter_policy": starter_policy,
            "counts": counts,
            "results": results,
        }
    )


if __name__ == "__main__":
    main()
