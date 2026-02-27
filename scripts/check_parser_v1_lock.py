#!/usr/bin/env python3
"""Check parser_v1 file drift against a frozen lock manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "quality" / "parser_v1_lock_manifest_2026-02-27.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Check parser_v1 lock manifest")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    manifest = _load_json(args.manifest)
    file_rows = list(manifest.get("file_hashes") or [])
    failures: list[dict[str, Any]] = []
    checked = 0

    for row in file_rows:
        rel = str(row.get("path") or "").strip()
        expected = str(row.get("sha256") or "").strip()
        if not rel or not expected:
            continue
        checked += 1
        path = ROOT / rel
        if not path.exists():
            failures.append({"path": rel, "reason": "missing_file"})
            continue
        actual = _sha256(path)
        if actual != expected:
            failures.append(
                {
                    "path": rel,
                    "reason": "hash_mismatch",
                    "expected": expected,
                    "actual": actual,
                },
            )

    payload = {
        "status": "pass" if not failures else "fail",
        "ok": not failures,
        "manifest": str(args.manifest),
        "checked_files": checked,
        "failures": failures,
    }
    print(json.dumps(payload, indent=2) if args.json else json.dumps({"status": payload["status"], "checked_files": checked, "failures": len(failures)}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
