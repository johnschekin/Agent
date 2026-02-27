#!/usr/bin/env python3
"""Replay parser over gold fixtures and enforce decision/category budgets.

This gate re-parses fixture text using the current parser implementation and
compares clause-level outputs against fixture gold nodes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.clause_parser import parse_clauses  # noqa: E402

DEFAULT_FIXTURES = ROOT / "data" / "fixtures" / "gold" / "v1" / "gates" / "replay_smoke_v1.jsonl"
DEFAULT_THRESHOLDS = ROOT / "config" / "gold_replay_gate_thresholds.json"

VALID_DECISIONS = {"accepted", "review", "abstain"}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing fixtures file: {path}")
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


def _parse_categories(raw: str) -> set[str]:
    raw = str(raw or "").strip()
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _build_actual_map(raw_text: str, char_start: int) -> dict[str, dict[str, Any]]:
    nodes = parse_clauses(raw_text, global_offset=char_start)
    out: dict[str, dict[str, Any]] = {}
    for node in nodes:
        span_start = int(node.span_start)
        span_end = int(node.span_end)
        if span_end < span_start:
            span_end = span_start
        out[str(node.id)] = {
            "clause_id": str(node.id),
            "parent_id": str(node.parent_id),
            "depth": int(node.depth),
            "level_type": str(node.level_type),
            "span_start": span_start,
            "span_end": span_end,
            "is_structural": bool(node.is_structural_candidate),
            "xref_suspected": bool(node.xref_suspected),
            "parse_confidence": float(node.parse_confidence),
        }
    return out


def _fixture_gold_map(fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = list(fixture.get("gold_nodes") or [])
    out: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        clause_id = str(node.get("clause_id") or "").strip()
        if not clause_id:
            continue
        out[clause_id] = {
            "clause_id": clause_id,
            "parent_id": str(node.get("parent_id") or ""),
            "depth": int(node.get("depth") or 0),
            "level_type": str(node.get("level_type") or ""),
            "span_start": int(node.get("span_start") or 0),
            "span_end": int(node.get("span_end") or 0),
            "is_structural": bool(node.get("is_structural")),
            "xref_suspected": bool(node.get("xref_suspected")),
        }
    return out


def _eval_fixture(
    fixture: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    fixture_id = str(fixture.get("fixture_id") or "")
    decision = str(fixture.get("gold_decision") or "").strip()
    category = str(fixture.get("category") or "").strip()
    source = fixture.get("source") or {}
    text = fixture.get("text") or {}
    raw_text = str(text.get("raw_text") or "")
    char_start = int(text.get("char_start") or 0)

    if not raw_text:
        return {
            "fixture_id": fixture_id,
            "category": category,
            "decision": decision,
            "ok": False,
            "error": "missing_raw_text",
        }

    gold_map = _fixture_gold_map(fixture)
    actual_map = _build_actual_map(raw_text, char_start)

    gold_ids = set(gold_map.keys())
    actual_ids = set(actual_map.keys())
    matched_ids = sorted(gold_ids & actual_ids)
    missing_ids = sorted(gold_ids - actual_ids)
    extra_ids = sorted(actual_ids - gold_ids)

    compare_fields = ("parent_id", "depth", "level_type", "is_structural", "xref_suspected")
    field_mismatch_count = 0
    span_mismatch_count = 0
    mismatch_samples: list[dict[str, Any]] = []
    def _num(key: str, default: float) -> float:
        value = policy.get(key, default)
        if value is None:
            return float(default)
        return float(value)

    span_tolerance = int(_num("span_tolerance", 0.0))

    for clause_id in matched_ids:
        gold = gold_map[clause_id]
        actual = actual_map[clause_id]
        field_mismatches: dict[str, dict[str, Any]] = {}
        for field in compare_fields:
            if gold[field] != actual[field]:
                field_mismatch_count += 1
                field_mismatches[field] = {"gold": gold[field], "actual": actual[field]}

        start_delta = abs(int(gold["span_start"]) - int(actual["span_start"]))
        end_delta = abs(int(gold["span_end"]) - int(actual["span_end"]))
        if start_delta > span_tolerance or end_delta > span_tolerance:
            span_mismatch_count += 1
            field_mismatches["span"] = {
                "gold": [int(gold["span_start"]), int(gold["span_end"])],
                "actual": [int(actual["span_start"]), int(actual["span_end"])],
                "delta": [start_delta, end_delta],
                "tolerance": span_tolerance,
            }

        if field_mismatches and len(mismatch_samples) < 10:
            mismatch_samples.append(
                {
                    "clause_id": clause_id,
                    "mismatches": field_mismatches,
                },
            )

    recall = (len(matched_ids) / len(gold_ids)) if gold_ids else 1.0
    precision = (len(matched_ids) / len(actual_ids)) if actual_ids else 1.0
    field_total = max(1, len(matched_ids) * len(compare_fields))
    field_mismatch_ratio = field_mismatch_count / field_total
    span_mismatch_ratio = span_mismatch_count / max(1, len(matched_ids))

    abstain_threshold = _num("abstain_confidence_threshold", 0.5)
    abstain_signal = any(
        (not bool(node["is_structural"])) or float(node["parse_confidence"]) < abstain_threshold
        for node in actual_map.values()
    )
    gold_abstain_signal = any(not bool(node["is_structural"]) for node in gold_map.values())

    reasons: list[str] = []
    if recall < _num("min_node_recall", 0.0):
        reasons.append("node_recall_below_threshold")
    if precision < _num("min_node_precision", 0.0):
        reasons.append("node_precision_below_threshold")
    if field_mismatch_ratio > _num("max_field_mismatch_ratio", 1.0):
        reasons.append("field_mismatch_ratio_above_threshold")
    if span_mismatch_ratio > _num("max_span_mismatch_ratio", 1.0):
        reasons.append("span_mismatch_ratio_above_threshold")
    if len(missing_ids) > int(_num("max_missing_nodes", 1_000_000)):
        reasons.append("missing_nodes_above_threshold")
    if len(extra_ids) > int(_num("max_extra_nodes", 1_000_000)):
        reasons.append("extra_nodes_above_threshold")
    if (
        bool(policy.get("require_abstain_signal", False))
        and gold_abstain_signal
        and not abstain_signal
    ):
        reasons.append("missing_abstain_signal")

    return {
        "fixture_id": fixture_id,
        "category": category,
        "decision": decision,
        "doc_id": str(source.get("doc_id") or ""),
        "section_number": str(source.get("section_number") or ""),
        "ok": not reasons,
        "reasons": reasons,
        "metrics": {
            "gold_node_count": len(gold_ids),
            "actual_node_count": len(actual_ids),
            "matched_node_count": len(matched_ids),
            "missing_node_count": len(missing_ids),
            "extra_node_count": len(extra_ids),
            "node_recall": round(recall, 6),
            "node_precision": round(precision, 6),
            "field_mismatch_count": field_mismatch_count,
            "field_mismatch_ratio": round(field_mismatch_ratio, 6),
            "span_mismatch_count": span_mismatch_count,
            "span_mismatch_ratio": round(span_mismatch_ratio, 6),
            "abstain_signal": abstain_signal,
            "gold_abstain_signal": gold_abstain_signal,
        },
        "samples": {
            "missing_ids": missing_ids[:10],
            "extra_ids": extra_ids[:10],
            "mismatches": mismatch_samples,
        },
    }


def run_gate(
    fixtures_path: Path,
    thresholds_path: Path,
    *,
    categories_filter: set[str],
    limit: int,
) -> dict[str, Any]:
    thresholds = _load_json(thresholds_path)
    decision_policies = dict(thresholds.get("decision_policies") or {})
    for decision in VALID_DECISIONS:
        if decision not in decision_policies:
            raise ValueError(f"Missing decision policy for {decision!r} in {thresholds_path}")

    fixtures = _load_jsonl(fixtures_path)
    if categories_filter:
        fixtures = [
            fx for fx in fixtures if str(fx.get("category") or "").strip() in categories_filter
        ]
    fixtures.sort(key=lambda fx: str(fx.get("fixture_id") or ""))
    if limit > 0:
        fixtures = fixtures[:limit]

    if not fixtures:
        raise ValueError("No fixtures selected for replay")

    results = []
    errors = []
    for fx in fixtures:
        decision = str(fx.get("gold_decision") or "").strip()
        if decision not in VALID_DECISIONS:
            results.append(
                {
                    "fixture_id": str(fx.get("fixture_id") or ""),
                    "category": str(fx.get("category") or ""),
                    "decision": decision,
                    "ok": False,
                    "error": f"invalid_decision:{decision}",
                },
            )
            continue
        policy = decision_policies.get(decision) or {}
        try:
            result = _eval_fixture(fx, policy)
        except Exception as exc:  # noqa: BLE001
            result = {
                "fixture_id": str(fx.get("fixture_id") or ""),
                "category": str(fx.get("category") or ""),
                "decision": decision,
                "ok": False,
                "error": f"replay_exception:{type(exc).__name__}:{exc}",
            }
        if not result.get("ok", False):
            errors.append(result)
        results.append(result)

    fail_by_decision = Counter(str(r.get("decision") or "") for r in errors)
    fail_by_category = Counter(str(r.get("category") or "") for r in errors)

    budgets = thresholds.get("failure_budgets") or {}
    by_decision_budget = dict((budgets.get("by_decision") or {}))
    by_category_cfg = dict((budgets.get("by_category") or {}))
    by_category_default = int(by_category_cfg.get("default", 0) or 0)
    by_category_overrides = dict((by_category_cfg.get("overrides") or {}))

    budget_breaches: list[dict[str, Any]] = []
    for decision, count in sorted(fail_by_decision.items()):
        budget = int(by_decision_budget.get(decision, 0) or 0)
        if count > budget:
            budget_breaches.append(
                {
                    "scope": "decision",
                    "key": decision,
                    "budget": budget,
                    "actual": count,
                },
            )
    for category, count in sorted(fail_by_category.items()):
        budget = int(by_category_overrides.get(category, by_category_default) or 0)
        if count > budget:
            budget_breaches.append(
                {
                    "scope": "category",
                    "key": category,
                    "budget": budget,
                    "actual": count,
                },
            )

    summary = {
        "fixtures_total": len(results),
        "fixtures_failed": len(errors),
        "fail_by_decision": dict(sorted(fail_by_decision.items())),
        "fail_by_category": dict(sorted(fail_by_category.items())),
        "pass_by_decision": dict(
            sorted(Counter(str(r.get("decision") or "") for r in results if r.get("ok")).items()),
        ),
        "pass_by_category": dict(
            sorted(Counter(str(r.get("category") or "") for r in results if r.get("ok")).items()),
        ),
    }
    ok = len(budget_breaches) == 0
    return {
        "status": "pass" if ok else "fail",
        "ok": ok,
        "fixtures": str(fixtures_path),
        "thresholds": str(thresholds_path),
        "summary": summary,
        "budget_breaches": budget_breaches,
        "failures": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay parser over gold fixtures")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--categories", default="", help="Optional comma-separated category filter")
    parser.add_argument("--limit", type=int, default=0, help="Optional max fixtures")
    parser.add_argument("--json", action="store_true", help="Emit full JSON payload")
    parser.add_argument("--max-failures-output", type=int, default=200, help="Truncate failures list in output")
    args = parser.parse_args()

    payload = run_gate(
        args.fixtures,
        args.thresholds,
        categories_filter=_parse_categories(args.categories),
        limit=int(args.limit or 0),
    )
    if args.max_failures_output >= 0:
        payload["failures"] = list(payload.get("failures") or [])[: args.max_failures_output]
    print(json.dumps(payload if args.json else {"status": payload["status"], "summary": payload["summary"]}, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
