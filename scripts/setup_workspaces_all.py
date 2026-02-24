#!/usr/bin/env python3
"""Batch workspace setup for all ontology families.

Runs `scripts/setup_workspace.py` once per ontology family with deterministic
family-id targeting and writes an aggregate summary.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import orjson

    def _load_json(path: Path) -> Any:
        return orjson.loads(path.read_bytes())

    def _dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def _write_json(path: Path, obj: object) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except ImportError:

    def _load_json(path: Path) -> Any:
        with path.open() as f:
            return json.load(f)

    def _dump_json(obj: object) -> None:
        print(json.dumps(obj, indent=2, default=str))

    def _write_json(path: Path, obj: object) -> None:
        path.write_text(json.dumps(obj, indent=2, default=str))


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _slug(text: str) -> str:
    lowered = text.strip().lower()
    lowered = lowered.replace("-", "_").replace(" ", "_")
    lowered = re.sub(r"[^a-z0-9_]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered)
    return lowered.strip("_")


@dataclass(frozen=True, slots=True)
class FamilyNode:
    family_id: str
    name: str
    tail: str


def _collect_family_nodes(ontology: object) -> list[FamilyNode]:
    families: list[FamilyNode] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if str(node.get("type", "")).strip().lower() == "family":
                family_id = str(node.get("id", "")).strip()
                name = str(node.get("name", "")).strip()
                if family_id:
                    tail = family_id.split(".")[-1]
                    families.append(FamilyNode(family_id=family_id, name=name, tail=tail))
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(ontology)
    return families


def _workspace_key_map(families: list[FamilyNode]) -> dict[str, str]:
    tail_counts: dict[str, int] = {}
    for family in families:
        tail_counts[family.tail] = tail_counts.get(family.tail, 0) + 1

    out: dict[str, str] = {}
    for family in families:
        if tail_counts[family.tail] == 1:
            out[family.family_id] = _slug(family.tail)
        else:
            out[family.family_id] = _slug(family.family_id.replace(".", "_"))
    return out


def _resolve_expert_materials(
    expert_root: Path,
    *,
    family_id: str,
    family_key: str,
    tail: str,
) -> Path | None:
    candidates = [
        expert_root / family_key,
        expert_root / family_id,
        expert_root / family_id.replace(".", "_"),
        expert_root / tail,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize workspaces for all ontology families.")
    parser.add_argument("--ontology", required=True, help="Path to ontology JSON.")
    parser.add_argument(
        "--bootstrap",
        default=None,
        help="Optional bootstrap strategies JSON path.",
    )
    parser.add_argument(
        "--workspace-root",
        default="workspaces",
        help="Workspace root directory (default: workspaces).",
    )
    parser.add_argument(
        "--expert-root",
        default=None,
        help="Optional root directory containing per-family expert material folders.",
    )
    parser.add_argument(
        "--only-family-ids",
        default=None,
        help="Optional comma-separated list of ontology family IDs to process.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to invoke setup_workspace.py.",
    )
    parser.add_argument(
        "--force-existing",
        action="store_true",
        help="Process existing workspace directories instead of skipping them.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first family setup failure.",
    )
    parser.add_argument(
        "--summary-out",
        default=None,
        help="Optional output path for summary JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only; do not invoke setup_workspace.py.",
    )
    args = parser.parse_args()

    ontology_path = Path(args.ontology)
    if not ontology_path.exists():
        _log(f"Error: ontology file not found at {ontology_path}")
        sys.exit(1)

    ontology = _load_json(ontology_path)
    families = _collect_family_nodes(ontology)
    if not families:
        _log("Error: no family nodes found in ontology.")
        sys.exit(1)

    selected_ids: set[str] | None = None
    if args.only_family_ids:
        selected_ids = {
            val.strip()
            for val in str(args.only_family_ids).split(",")
            if val.strip()
        }
        families = [fam for fam in families if fam.family_id in selected_ids]

    workspace_root = Path(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)

    bootstrap_path = Path(args.bootstrap) if args.bootstrap else None
    if bootstrap_path is not None and not bootstrap_path.exists():
        _log(f"Error: bootstrap file not found at {bootstrap_path}")
        sys.exit(1)

    expert_root = Path(args.expert_root) if args.expert_root else None
    if expert_root is not None and not expert_root.exists():
        _log(f"Error: expert root not found at {expert_root}")
        sys.exit(1)

    key_map = _workspace_key_map(families)
    setup_script = Path(__file__).resolve().parent / "setup_workspace.py"

    rows: list[dict[str, Any]] = []
    created = 0
    skipped = 0
    failed = 0
    started_at = datetime.now(UTC)

    for idx, family in enumerate(families, start=1):
        family_key = key_map[family.family_id]
        workspace_dir = workspace_root / family_key
        row: dict[str, Any] = {
            "index": idx,
            "family_id": family.family_id,
            "family_name": family.name,
            "family_tail": family.tail,
            "workspace_key": family_key,
            "workspace": str(workspace_dir),
            "status": "pending",
        }

        if workspace_dir.exists() and not args.force_existing:
            row["status"] = "skipped_existing"
            skipped += 1
            rows.append(row)
            _log(f"[{idx}/{len(families)}] skip {family.family_id} (existing workspace)")
            continue

        cmd = [
            str(args.python),
            str(setup_script),
            "--family",
            family.tail,
            "--family-id",
            family.family_id,
            "--ontology",
            str(ontology_path),
            "--output",
            str(workspace_dir),
        ]
        if bootstrap_path is not None:
            cmd.extend(["--bootstrap", str(bootstrap_path)])
        if expert_root is not None:
            expert_dir = _resolve_expert_materials(
                expert_root,
                family_id=family.family_id,
                family_key=family_key,
                tail=family.tail,
            )
            if expert_dir is not None:
                cmd.extend(["--expert-materials", str(expert_dir)])
                row["expert_materials"] = str(expert_dir)

        row["command"] = cmd
        if args.dry_run:
            row["status"] = "planned"
            rows.append(row)
            _log(f"[{idx}/{len(families)}] plan {family.family_id} -> {workspace_dir}")
            continue

        _log(f"[{idx}/{len(families)}] setup {family.family_id} -> {workspace_dir}")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        row["returncode"] = proc.returncode
        if proc.stdout.strip():
            try:
                row["result"] = json.loads(proc.stdout)
            except json.JSONDecodeError:
                row["stdout"] = proc.stdout.strip()
        if proc.stderr.strip():
            row["stderr"] = proc.stderr.strip()

        if proc.returncode == 0:
            row["status"] = "created"
            created += 1
        else:
            row["status"] = "failed"
            failed += 1
            if args.fail_fast:
                rows.append(row)
                payload = {
                    "schema_version": "setup_workspaces_all_v1",
                    "generated_at": datetime.now(UTC).isoformat(),
                    "ontology": str(ontology_path),
                    "workspace_root": str(workspace_root),
                    "summary": {
                        "selected_families": len(families),
                        "created": created,
                        "skipped_existing": skipped,
                        "failed": failed,
                        "dry_run": bool(args.dry_run),
                        "fail_fast": True,
                    },
                    "rows": rows,
                }
                if args.summary_out:
                    out_path = Path(args.summary_out)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    _write_json(out_path, payload)
                _dump_json(payload)
                sys.exit(1)

        rows.append(row)

    completed_at = datetime.now(UTC)
    payload = {
        "schema_version": "setup_workspaces_all_v1",
        "generated_at": completed_at.isoformat(),
        "ontology": str(ontology_path),
        "workspace_root": str(workspace_root),
        "summary": {
            "selected_families": len(families),
            "created": created,
            "skipped_existing": skipped,
            "failed": failed,
            "dry_run": bool(args.dry_run),
            "force_existing": bool(args.force_existing),
            "duration_sec": round((completed_at - started_at).total_seconds(), 3),
        },
        "rows": rows,
    }
    if selected_ids is not None:
        payload["selected_family_ids"] = sorted(selected_ids)

    if args.summary_out:
        out_path = Path(args.summary_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(out_path, payload)
    _dump_json(payload)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
