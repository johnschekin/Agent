#!/usr/bin/env python3
"""Migrate evidence schema payloads with idempotent evidence_v2 -> evidence_v3 conversion.

This script is the plan-facing wrapper used in PR-8. It supports single-file
or directory migration and produces deterministic checksums/reports.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_converter() -> Any:
    script_path = Path(__file__).resolve().parent / "migrate_evidence_v2_to_v3.py"
    spec = importlib.util.spec_from_file_location("migrate_evidence_v2_to_v3", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load converter script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.jsonl"))
    return []


def _output_path_for(input_file: Path, input_root: Path, output_root: Path) -> Path:
    if input_root.is_file():
        return output_root
    rel = input_file.relative_to(input_root)
    stem = rel.stem
    if not stem.endswith(".v3"):
        stem = f"{stem}.v3"
    return output_root / rel.with_name(f"{stem}{rel.suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate evidence payloads to evidence_v3.")
    parser.add_argument("--input", required=True, help="Input file or directory")
    parser.add_argument("--output", required=True, help="Output file or directory")
    parser.add_argument("--dry-run", action="store_true", help="Do not write migrated output")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    files = _collect_input_files(in_path)
    if not files:
        raise SystemExit(f"No JSONL inputs found at: {in_path}")

    converter = _load_converter()
    normalize_v2 = converter._normalize_v2_row

    reports: list[dict[str, Any]] = []
    totals = {"v2_to_v3": 0, "v3_passthrough": 0, "other_skipped": 0}

    for input_file in files:
        rows_out: list[dict[str, Any]] = []
        counts = {"v2_to_v3": 0, "v3_passthrough": 0, "other_skipped": 0}
        for line in input_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                counts["other_skipped"] += 1
                continue
            schema = str(row.get("schema_version") or "").strip()
            if schema == "evidence_v3":
                rows_out.append(row)
                counts["v3_passthrough"] += 1
                continue
            if schema in {"", "evidence_v2"}:
                rows_out.append(normalize_v2(row))
                counts["v2_to_v3"] += 1
                continue
            counts["other_skipped"] += 1

        for key, value in counts.items():
            totals[key] += int(value)

        output_file = _output_path_for(input_file, in_path, out_path)
        if not args.dry_run:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with output_file.open("w") as f:
                for row in rows_out:
                    f.write(json.dumps(row))
                    f.write("\n")

        reports.append(
            {
                "input": str(input_file),
                "output": str(output_file),
                "counts": counts,
                "input_sha256": _file_sha256(input_file),
                "output_sha256": _file_sha256(output_file) if output_file.exists() else "",
            }
        )

    print(
        json.dumps(
            {
                "status": "dry_run" if args.dry_run else "ok",
                "input": str(in_path),
                "output": str(out_path),
                "file_count": len(files),
                "totals": totals,
                "files": reports,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
