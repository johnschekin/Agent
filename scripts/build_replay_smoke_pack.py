#!/usr/bin/env python3
"""Build a compact replay fixture pack for CI.

Creates a small corpus-backed fixture JSONL with category coverage and short
section lengths, then freezes gold nodes from the current parser output.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.clause_parser import parse_clauses  # noqa: E402

DEFAULT_SOURCE = ROOT / "data" / "fixtures" / "gold" / "v1" / "packs" / "v1-seed-1000-candidate" / "fixtures.jsonl"
DEFAULT_OUT = ROOT / "data" / "fixtures" / "gold" / "v1" / "gates" / "replay_smoke_v1.jsonl"
DEFAULT_MANIFEST = ROOT / "data" / "fixtures" / "gold" / "v1" / "gates" / "replay_smoke_v1.manifest.json"
DEFAULT_TARGETS = {
    "ambiguous_alpha_roman": 4,
    "high_letter_continuation": 10,
    "nonstruct_parent_chain": 4,
    "xref_vs_structural": 10,
    "true_root_high_letter": 6,
    "defined_term_boundary": 4,
    "linking_contract": 10,
    "formatting_noise": 4,
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing source fixture file: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{idx}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object at {path}:{idx}")
            rows.append(row)
    return rows


def _parse_targets(raw: str) -> dict[str, int]:
    raw = str(raw or "").strip()
    if not raw:
        raise ValueError("Empty targets string")
    out: dict[str, int] = {}
    for token in [p.strip() for p in raw.split(",") if p.strip()]:
        if ":" not in token:
            raise ValueError(f"Invalid target token (expected category:count): {token}")
        category, count_s = token.split(":", 1)
        category = category.strip()
        count = int(count_s.strip())
        if not category:
            raise ValueError(f"Empty category in target token: {token}")
        if count <= 0:
            raise ValueError(f"Target count must be > 0: {token}")
        out[category] = count
    return out


def _write_jsonl(path: Path, rows: list[dict[str, Any]], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output exists: {path}. Pass --overwrite to replace.")
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _section_key(fixture: dict[str, Any]) -> tuple[str, str]:
    source = fixture.get("source") or {}
    return (
        str(source.get("doc_id") or "").strip(),
        str(source.get("section_number") or "").strip(),
    )


def _build_gold_nodes(raw_text: str, char_start: int) -> list[dict[str, Any]]:
    nodes = parse_clauses(raw_text, global_offset=char_start)
    gold_nodes: list[dict[str, Any]] = []
    for node in nodes:
        span_start = int(node.span_start)
        span_end = int(node.span_end)
        if span_end < span_start:
            span_end = span_start
        gold_nodes.append(
            {
                "clause_id": str(node.id),
                "label": str(node.label),
                "parent_id": str(node.parent_id),
                "depth": int(node.depth),
                "level_type": str(node.level_type),
                "span_start": span_start,
                "span_end": span_end,
                "is_structural": bool(node.is_structural_candidate),
                "xref_suspected": bool(node.xref_suspected),
                "confidence_band": (
                    "high"
                    if float(node.parse_confidence) >= 0.8
                    else "medium"
                    if float(node.parse_confidence) >= 0.5
                    else "low"
                ),
            },
        )
    return gold_nodes


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact replay smoke fixture pack")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Source fixture JSONL")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output replay-smoke fixture JSONL")
    parser.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST, help="Output manifest JSON")
    parser.add_argument("--max-text-len", type=int, default=70_000, help="Max raw_text length")
    parser.add_argument(
        "--targets",
        default=",".join(f"{k}:{v}" for k, v in DEFAULT_TARGETS.items()),
        help="Comma-separated category targets",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite outputs")
    args = parser.parse_args()

    targets = _parse_targets(args.targets)
    source_rows = _load_jsonl(args.source)

    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in source_rows:
        category = str(row.get("category") or "").strip()
        if category not in targets:
            continue
        raw_text = str((row.get("text") or {}).get("raw_text") or "")
        if not raw_text:
            continue
        if len(raw_text) > args.max_text_len:
            continue
        by_category.setdefault(category, []).append(row)

    selected: list[dict[str, Any]] = []
    used_sections: set[tuple[str, str]] = set()
    for category, need in targets.items():
        candidates = list(by_category.get(category) or [])
        candidates.sort(
            key=lambda row: (
                len(str((row.get("text") or {}).get("raw_text") or "")),
                -float((row.get("source") or {}).get("candidate_score") or 0.0),
                str(row.get("fixture_id") or ""),
            ),
        )
        taken = 0
        for row in candidates:
            if taken >= need:
                break
            key = _section_key(row)
            if key in used_sections:
                continue
            used_sections.add(key)
            selected.append(row)
            taken += 1
        if taken < need:
            raise RuntimeError(
                f"Insufficient candidates for category {category!r}: need {need}, got {taken}",
            )

    selected.sort(key=lambda row: (str(row.get("category") or ""), str(row.get("fixture_id") or "")))

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(selected, start=1):
        text = row.get("text") or {}
        raw_text = str(text.get("raw_text") or "")
        char_start = int(text.get("char_start") or 0)
        category = str(row.get("category") or "").strip()
        fixture = {
            "fixture_id": f"GRV1-{category.upper().replace('-', '_')}-{idx:04d}",
            "schema_version": "gold-fixture-v1",
            "category": category,
            "source_type": str(row.get("source_type") or "corpus"),
            "source": dict(row.get("source") or {}),
            "text": {
                "raw_text": raw_text,
                "char_start": char_start,
                "char_end": int(text.get("char_end") or (char_start + len(raw_text))),
                "normalization": dict(text.get("normalization") or {}),
            },
            "section_meta": dict(row.get("section_meta") or {}),
            "gold_nodes": _build_gold_nodes(raw_text, char_start),
            "gold_decision": str(row.get("gold_decision") or "review"),
            "reason_codes": list(row.get("reason_codes") or []),
            "adjudication": {
                **dict(row.get("adjudication") or {}),
                "human_verified": False,
                "adjudicator_id": "replay_smoke_freeze_v1",
                "adjudicated_at": None,
                "rationale": f"Frozen from parser output for replay smoke gate at {created_at}",
            },
            "split": str(row.get("split") or "train"),
            "tags": sorted(set(list(row.get("tags") or []) + ["replay_smoke", "parser_gate"])),
        }
        output_rows.append(fixture)

    _write_jsonl(args.out, output_rows, overwrite=args.overwrite)

    cat_counts = Counter(str(fx.get("category") or "") for fx in output_rows)
    split_counts = Counter(str(fx.get("split") or "") for fx in output_rows)
    decision_counts = Counter(str(fx.get("gold_decision") or "") for fx in output_rows)
    manifest = {
        "version": "gold-replay-smoke-v1",
        "created_at": created_at,
        "source": str(args.source),
        "out": str(args.out),
        "targets": targets,
        "max_text_len": int(args.max_text_len),
        "counts": {
            "fixtures": len(output_rows),
            "by_category": dict(sorted(cat_counts.items())),
            "by_split": dict(sorted(split_counts.items())),
            "by_decision": dict(sorted(decision_counts.items())),
        },
        "notes": "Gold nodes frozen from current parser output.",
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    if args.manifest_out.exists() and not args.overwrite:
        raise FileExistsError(f"Manifest exists: {args.manifest_out}. Pass --overwrite to replace.")
    args.manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", **manifest["counts"], "manifest_out": str(args.manifest_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
