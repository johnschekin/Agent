#!/usr/bin/env python3
"""Promote selected strategy JSON files from v1 to v2 with starter policies.

Usage:
    python3 scripts/migrate_strategy_v1_to_v2.py \
      --path workspaces/indebtedness/strategies \
      --recursive \
      --concept-prefix debt_capacity.indebtedness \
      --dry-run

The migration sets:
  - acceptance_policy_version: "v2"
  - outlier_policy (starter keys)
  - template_stability_policy (starter keys)
  - did_not_find_policy (starter keys)

By default existing policy values are preserved; missing keys are added.
Use --force to overwrite starter keys.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from agent.strategy import normalize_template_overrides

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


def collect_strategy_files(root: Path, *, recursive: bool, pattern: str) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    if recursive:
        return sorted(p for p in root.rglob(pattern) if p.is_file())
    return sorted(p for p in root.glob(pattern) if p.is_file())


def build_starter_policies(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    return {
        "outlier_policy": {
            "max_outlier_rate": float(args.max_outlier_rate),
            "max_high_risk_rate": float(args.max_high_risk_rate),
            "max_review_rate": float(args.max_review_rate),
            "sample_size": int(args.sample_size),
        },
        "template_stability_policy": {
            "min_group_size": int(args.min_group_size),
            "min_groups": int(args.min_groups),
            "min_group_hit_rate": float(args.min_group_hit_rate),
            "max_group_hit_rate_gap": float(args.max_group_hit_rate_gap),
        },
        "did_not_find_policy": {
            "min_coverage": float(args.min_coverage),
            "max_near_miss_rate": float(args.max_near_miss_rate),
            "max_near_miss_count": int(args.max_near_miss_count),
        },
    }


def _concept_id(payload: dict[str, Any]) -> str:
    for key in ("concept_id", "id"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _matches_globs(path: Path, include_globs: list[str], exclude_globs: list[str]) -> bool:
    rel = path.as_posix()
    name = path.name
    if include_globs and not any(
        fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g)
        for g in include_globs
    ):
        return False
    return not (
        exclude_globs
        and any(
            fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g)
            for g in exclude_globs
        )
    )


def _matches_selection(
    payload: dict[str, Any],
    *,
    path: Path,
    concept_ids: set[str],
    concept_prefixes: tuple[str, ...],
    include_globs: list[str],
    exclude_globs: list[str],
) -> bool:
    if not _matches_globs(path, include_globs, exclude_globs):
        return False

    cid = _concept_id(payload)
    if concept_ids and cid not in concept_ids:
        return False
    return not (
        concept_prefixes
        and not any(cid.startswith(prefix) for prefix in concept_prefixes)
    )


def _merge_policy(
    *,
    current: Any,
    starter: dict[str, Any],
    force: bool,
) -> tuple[dict[str, Any], bool]:
    changed = False
    merged: dict[str, Any]
    if isinstance(current, dict):
        merged = dict(current)
    else:
        merged = {}
        changed = True

    for key, value in starter.items():
        if force:
            if merged.get(key) != value:
                merged[key] = value
                changed = True
        elif key not in merged:
            merged[key] = value
            changed = True
    return merged, changed


def migrate_strategy_payload(
    payload: object,
    *,
    starter_policies: dict[str, dict[str, Any]],
    force: bool,
    concept_ids: set[str],
    concept_prefixes: tuple[str, ...],
    path: Path,
    include_globs: list[str],
    exclude_globs: list[str],
) -> tuple[object, bool, str]:
    """Return (updated_payload, changed, status_code)."""
    if not isinstance(payload, dict):
        return payload, False, "skip_non_object"

    if not _matches_selection(
        payload,
        path=path,
        concept_ids=concept_ids,
        concept_prefixes=concept_prefixes,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
    ):
        return payload, False, "skip_filtered"

    current_ver = str(payload.get("acceptance_policy_version", "v1")).strip().lower()
    if current_ver == "v2" and not force:
        return payload, False, "skip_already_v2"
    if current_ver not in {"v1", "v2"} and not force:
        return payload, False, "skip_unsupported_version"

    changed = False
    if payload.get("acceptance_policy_version") != "v2":
        payload["acceptance_policy_version"] = "v2"
        changed = True

    for field_name, starter in starter_policies.items():
        merged, policy_changed = _merge_policy(
            current=payload.get(field_name),
            starter=starter,
            force=force,
        )
        payload[field_name] = merged
        changed = changed or policy_changed

    if "template_overrides" in payload:
        normalized_overrides = normalize_template_overrides(payload.get("template_overrides"))
        if payload.get("template_overrides") != normalized_overrides:
            payload["template_overrides"] = normalized_overrides
            changed = True

    if changed:
        return payload, True, "updated"
    return payload, False, "skip_already_configured"


def migrate_file(
    path: Path,
    *,
    starter_policies: dict[str, dict[str, Any]],
    force: bool,
    dry_run: bool,
    backup: bool,
    concept_ids: set[str],
    concept_prefixes: tuple[str, ...],
    include_globs: list[str],
    exclude_globs: list[str],
) -> dict[str, Any]:
    try:
        payload = load_json(path)
    except Exception as exc:
        return {"path": str(path), "status": "error_parse", "error": str(exc)}

    updated, changed, status = migrate_strategy_payload(
        payload,
        starter_policies=starter_policies,
        force=force,
        concept_ids=concept_ids,
        concept_prefixes=concept_prefixes,
        path=path,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
    )

    result = {"path": str(path), "status": status, "changed": changed}
    if changed and not dry_run:
        if backup:
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)
            result["backup"] = str(backup_path)
        write_json(path, updated)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote selected strategy JSON files from v1 to v2 with starter policies."
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
        "--concept-id",
        action="append",
        default=[],
        help="Exact concept_id filter (repeatable).",
    )
    parser.add_argument(
        "--concept-prefix",
        action="append",
        default=[],
        help="concept_id prefix filter (repeatable).",
    )
    parser.add_argument(
        "--include-glob",
        action="append",
        default=[],
        help="Include file glob filter (repeatable; matches name or relative path).",
    )
    parser.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="Exclude file glob filter (repeatable; matches name or relative path).",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite starter policy keys.")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing files.")
    parser.add_argument("--backup", action="store_true", help="Create .bak files before writing.")

    # Starter outlier_policy knobs.
    parser.add_argument("--max-outlier-rate", type=float, default=0.10)
    parser.add_argument("--max-high-risk-rate", type=float, default=0.05)
    parser.add_argument("--max-review-rate", type=float, default=0.20)
    parser.add_argument("--sample-size", type=int, default=200)

    # Starter template_stability_policy knobs.
    parser.add_argument("--min-group-size", type=int, default=10)
    parser.add_argument("--min-groups", type=int, default=2)
    parser.add_argument("--min-group-hit-rate", type=float, default=0.60)
    parser.add_argument("--max-group-hit-rate-gap", type=float, default=0.25)

    # Starter did_not_find_policy knobs.
    parser.add_argument("--min-coverage", type=float, default=0.90)
    parser.add_argument("--max-near-miss-rate", type=float, default=0.15)
    parser.add_argument("--max-near-miss-count", type=int, default=10)

    args = parser.parse_args()

    root = Path(args.path)
    files = collect_strategy_files(root, recursive=args.recursive, pattern=args.pattern)
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

    concept_ids = {c.strip() for c in args.concept_id if c and c.strip()}
    concept_prefixes = tuple(c.strip() for c in args.concept_prefix if c and c.strip())
    starter_policies = build_starter_policies(args)

    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "updated": 0,
        "skip_non_object": 0,
        "skip_filtered": 0,
        "skip_already_v2": 0,
        "skip_unsupported_version": 0,
        "skip_already_configured": 0,
        "error_parse": 0,
    }
    for path in files:
        res = migrate_file(
            path,
            starter_policies=starter_policies,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
            backup=bool(args.backup),
            concept_ids=concept_ids,
            concept_prefixes=concept_prefixes,
            include_globs=list(args.include_glob),
            exclude_globs=list(args.exclude_glob),
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
            "force": bool(args.force),
            "selection": {
                "concept_ids": sorted(concept_ids),
                "concept_prefixes": list(concept_prefixes),
                "include_glob": list(args.include_glob),
                "exclude_glob": list(args.exclude_glob),
            },
            "starter_policies": starter_policies,
            "counts": counts,
            "results": results,
        }
    )


if __name__ == "__main__":
    main()
