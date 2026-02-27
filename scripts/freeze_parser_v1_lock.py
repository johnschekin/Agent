#!/usr/bin/env python3
"""Freeze parser_v1 lock manifest for parser_v2 migration.

Produces a manifest with:
1) tracked file hashes for parser_v1-critical files
2) baseline artifact references and hashes
3) git branch/sha metadata
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "parser_v1_lock_files.json"
DEFAULT_OUT = ROOT / "data" / "quality" / "parser_v1_lock_manifest_2026-02-27.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_output(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze parser_v1 lock manifest")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    cfg = _load_json(args.config)
    files = [str(v) for v in list(cfg.get("files") or []) if str(v).strip()]
    baseline_refs = dict(cfg.get("baseline_refs") or {})
    if not files:
        raise ValueError("No files listed in parser_v1 lock config")

    file_rows: list[dict[str, Any]] = []
    missing_files: list[str] = []
    for rel in files:
        path = ROOT / rel
        if not path.exists():
            missing_files.append(rel)
            continue
        file_rows.append(
            {
                "path": rel,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            },
        )

    baseline_rows: list[dict[str, Any]] = []
    for name, rel in baseline_refs.items():
        rel_s = str(rel)
        path = ROOT / rel_s
        baseline_rows.append(
            {
                "name": str(name),
                "path": rel_s,
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "sha256": _sha256(path) if path.exists() else "",
            },
        )

    manifest = {
        "version": "parser-v1-lock-manifest-v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git": {
            "branch": _git_output(["branch", "--show-current"]),
            "head_sha": _git_output(["rev-parse", "HEAD"]),
            "status_short": _git_output(["status", "--short"]),
        },
        "config_path": str(args.config.relative_to(ROOT)),
        "files_hashed": len(file_rows),
        "missing_files": missing_files,
        "file_hashes": file_rows,
        "baseline_artifacts": baseline_rows,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {args.out}. Pass --overwrite to replace.")
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "out": str(args.out), "files_hashed": len(file_rows), "missing_files": missing_files}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
