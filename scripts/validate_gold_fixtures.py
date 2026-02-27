#!/usr/bin/env python3
"""Validate v1 gold fixture packs.

Checks:
1) fixture schema essentials
2) reason-code validity and decision compatibility
3) fixture-id uniqueness
4) node-level basic integrity (IDs, parent links, spans)
5) split validity and doc-level no-overlap guarantee
6) optional split-manifest consistency
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "data" / "fixtures" / "gold" / "v1" / "fixtures.jsonl"
DEFAULT_REASON_CODES = ROOT / "data" / "fixtures" / "gold" / "v1" / "reason_codes.v1.json"
DEFAULT_SPLITS = ROOT / "data" / "fixtures" / "gold" / "v1" / "splits.v1.manifest.json"
VALID_SPLITS = {"train", "val", "test", "holdout"}
VALID_DECISIONS = {"accepted", "review", "abstain"}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _required_top_fields() -> tuple[str, ...]:
    return (
        "fixture_id",
        "schema_version",
        "category",
        "source_type",
        "source",
        "text",
        "gold_nodes",
        "gold_decision",
        "reason_codes",
        "adjudication",
        "split",
    )


def _required_node_fields() -> tuple[str, ...]:
    return (
        "clause_id",
        "label",
        "parent_id",
        "depth",
        "level_type",
        "span_start",
        "span_end",
        "is_structural",
        "xref_suspected",
    )


def _index_reason_codes(reason_codes_payload: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for item in list(reason_codes_payload.get("codes") or []):
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        allowed = {str(v).strip() for v in list(item.get("allowed_decisions") or []) if str(v).strip()}
        out[code] = allowed
    if not out:
        raise ValueError("No reason codes found in taxonomy file")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate v1 gold fixture packs.")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES, help="Fixture JSONL path")
    parser.add_argument("--reason-codes", type=Path, default=DEFAULT_REASON_CODES, help="Reason-code taxonomy JSON path")
    parser.add_argument("--split-manifest", type=Path, default=DEFAULT_SPLITS, help="Split manifest JSON path")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    args = parser.parse_args()

    fixtures = _load_jsonl(args.fixtures)
    reason_codes = _index_reason_codes(_load_json(args.reason_codes))
    split_manifest = _load_json(args.split_manifest) if args.split_manifest.exists() else None

    errors: list[str] = []
    warnings: list[str] = []
    fixture_ids: set[str] = set()
    doc_to_split: dict[str, str] = {}
    by_category = Counter()
    by_split = Counter()
    by_decision = Counter()

    for idx, fx in enumerate(fixtures, start=1):
        ref = f"fixture[{idx}]"
        for field in _required_top_fields():
            if field not in fx:
                errors.append(f"{ref}: missing required field '{field}'")

        fixture_id = str(fx.get("fixture_id") or "").strip()
        if not fixture_id:
            errors.append(f"{ref}: empty fixture_id")
        elif fixture_id in fixture_ids:
            errors.append(f"{ref}: duplicate fixture_id '{fixture_id}'")
        else:
            fixture_ids.add(fixture_id)

        schema_version = str(fx.get("schema_version") or "").strip()
        if schema_version != "gold-fixture-v1":
            errors.append(f"{ref}: schema_version must be 'gold-fixture-v1' (got '{schema_version}')")

        decision = str(fx.get("gold_decision") or "").strip()
        if decision not in VALID_DECISIONS:
            errors.append(f"{ref}: invalid gold_decision '{decision}'")

        split = str(fx.get("split") or "").strip()
        if split not in VALID_SPLITS:
            errors.append(f"{ref}: invalid split '{split}'")

        source = fx.get("source")
        if not isinstance(source, dict):
            errors.append(f"{ref}: source must be object")
            source = {}
        doc_id = str(source.get("doc_id") or "").strip()
        if not doc_id:
            warnings.append(f"{ref}: source.doc_id is empty")
        else:
            prev = doc_to_split.get(doc_id)
            if prev and prev != split:
                errors.append(
                    f"{ref}: doc_id '{doc_id}' assigned to multiple splits: {prev} vs {split}",
                )
            else:
                doc_to_split[doc_id] = split

        reason_list = list(fx.get("reason_codes") or [])
        if not reason_list:
            warnings.append(f"{ref}: no reason_codes")
        for reason in reason_list:
            code = str(reason or "").strip()
            if code not in reason_codes:
                errors.append(f"{ref}: unknown reason code '{code}'")
                continue
            allowed = reason_codes[code]
            if allowed and decision and decision not in allowed:
                errors.append(
                    f"{ref}: reason code '{code}' not allowed for decision '{decision}'",
                )

        text = fx.get("text")
        if not isinstance(text, dict):
            errors.append(f"{ref}: text must be object")
            text = {}
        raw_text = str(text.get("raw_text") or "")
        char_start = text.get("char_start")
        char_end = text.get("char_end")
        if not isinstance(char_start, int) or not isinstance(char_end, int):
            errors.append(f"{ref}: text.char_start/char_end must be integers")
            char_start = 0
            char_end = 0
        elif char_end < char_start:
            errors.append(f"{ref}: text.char_end < text.char_start")

        nodes = fx.get("gold_nodes")
        if not isinstance(nodes, list) or not nodes:
            errors.append(f"{ref}: gold_nodes must be a non-empty list")
            nodes = []

        clause_ids: set[str] = set()
        node_by_id: dict[str, dict[str, Any]] = {}
        for nidx, node in enumerate(nodes, start=1):
            nref = f"{ref}.gold_nodes[{nidx}]"
            if not isinstance(node, dict):
                errors.append(f"{nref}: node must be object")
                continue
            for field in _required_node_fields():
                if field not in node:
                    errors.append(f"{nref}: missing required field '{field}'")
            clause_id = str(node.get("clause_id") or "").strip()
            if not clause_id:
                errors.append(f"{nref}: empty clause_id")
            elif clause_id in clause_ids:
                errors.append(f"{nref}: duplicate clause_id '{clause_id}'")
            else:
                clause_ids.add(clause_id)
                node_by_id[clause_id] = node
            depth = node.get("depth")
            if not isinstance(depth, int) or depth < 0:
                errors.append(f"{nref}: invalid depth '{depth}'")
            span_start = node.get("span_start")
            span_end = node.get("span_end")
            if not isinstance(span_start, int) or not isinstance(span_end, int):
                errors.append(f"{nref}: span_start/span_end must be integers")
            elif span_end < span_start:
                errors.append(f"{nref}: span_end < span_start")
            elif raw_text:
                # Section-scope rough check: absolute spans should not be inverted.
                # No strict upper bound because spans are global offsets.
                pass

        for clause_id, node in node_by_id.items():
            parent_id = str(node.get("parent_id") or "").strip()
            if parent_id and parent_id not in node_by_id:
                warnings.append(
                    f"{ref}: node '{clause_id}' parent_id '{parent_id}' not in fixture node set",
                )

        category = str(fx.get("category") or "").strip()
        if not category:
            warnings.append(f"{ref}: empty category")

        by_category[category] += 1
        by_split[split] += 1
        by_decision[decision] += 1

    if split_manifest is not None:
        manifest_assignments = {
            str(row.get("doc_id") or "").strip(): str(row.get("split") or "").strip()
            for row in list(split_manifest.get("doc_assignments") or [])
            if str(row.get("doc_id") or "").strip()
        }
        for doc_id, split in doc_to_split.items():
            m_split = manifest_assignments.get(doc_id)
            if m_split and m_split != split:
                errors.append(
                    f"split-manifest mismatch: doc_id '{doc_id}' fixture split '{split}' vs manifest '{m_split}'",
                )

    payload = {
        "ok": not errors,
        "fixture_count": len(fixtures),
        "doc_count": len(doc_to_split),
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "by_category": dict(sorted(by_category.items())),
            "by_split": dict(sorted(by_split.items())),
            "by_decision": dict(sorted(by_decision.items())),
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"ok={payload['ok']} fixtures={payload['fixture_count']} docs={payload['doc_count']}")
        print(f"errors={len(errors)} warnings={len(warnings)}")
        for msg in errors[:30]:
            print(f"ERROR: {msg}")
        for msg in warnings[:20]:
            print(f"WARN: {msg}")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
