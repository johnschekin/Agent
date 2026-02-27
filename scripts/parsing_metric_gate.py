#!/usr/bin/env python3
"""Aggressive parser quality gate for corpus-level parsing metrics.

This gate enforces substantial improvements against the frozen parser baseline:
- Parser-integrity totals (`active` and `all`)
- Active parser-integrity category counts
- Monitor-only parser-integrity categories (configured subset)
- Clause-collision guardrail metrics
- x/y parent-loss guardrail metrics
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "corpus_index" / "corpus.duckdb"
DEFAULT_BASELINE = ROOT / "data" / "quality" / "parsing_baseline_freeze_2026-02-27.json"
DEFAULT_THRESHOLDS = ROOT / "config" / "parsing_metric_gate_thresholds.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[call-arg]
    return mod


def _metric_at(metrics: dict[str, Any], dotted: str) -> float:
    value: Any = metrics
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return float(value)


def _category_map(items: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in items:
        cat = str(row.get("category") or "").strip()
        if not cat:
            continue
        out[cat] = int(row.get("count", 0) or 0)
    return out


def _baseline_category_map(items: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in items:
        cat = str(row.get("category") or "").strip()
        if not cat:
            continue
        out[cat] = int(row.get("count", 0) or 0)
    return out


def _fetch_parser_integrity_snapshot(db_path: Path, cohort_only: bool) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    from agent.corpus import CorpusIndex  # noqa: PLC0415
    from dashboard.api import server  # noqa: PLC0415

    server._corpus = CorpusIndex(str(db_path))

    all_resp = asyncio.run(
        server.edge_cases(
            category="all",
            group="parser_integrity",
            detector_status="all",
            page=0,
            page_size=200,
            cohort_only=cohort_only,
        ),
    )
    active_resp = asyncio.run(
        server.edge_cases(
            category="all",
            group="parser_integrity",
            detector_status="active",
            page=0,
            page_size=200,
            cohort_only=cohort_only,
        ),
    )
    return {
        "all_total": int(all_resp.get("total", 0) or 0),
        "active_total": int(active_resp.get("total", 0) or 0),
        "all_categories": _category_map(list(all_resp.get("categories") or [])),
        "active_categories": _category_map(list(active_resp.get("categories") or [])),
    }


def _eval_metric(
    scope: str,
    metric: str,
    baseline: float,
    current: float,
    policy: dict[str, Any],
) -> dict[str, Any]:
    eps = 1e-12
    failed: list[dict[str, Any]] = []

    delta = current - baseline
    reduction = baseline - current
    reduction_ratio = (reduction / baseline) if baseline > 0 else 0.0

    max_abs_increase = (
        float(policy["max_abs_increase"]) if "max_abs_increase" in policy else None
    )
    max_rel_increase = (
        float(policy["max_rel_increase"]) if "max_rel_increase" in policy else None
    )
    min_abs_reduction = (
        float(policy["min_abs_reduction"]) if "min_abs_reduction" in policy else None
    )
    min_rel_reduction = (
        float(policy["min_rel_reduction"]) if "min_rel_reduction" in policy else None
    )
    min_baseline_for_reduction = float(policy.get("min_baseline_for_reduction", 0.0) or 0.0)
    max_current_value = (
        float(policy["max_current_value"]) if "max_current_value" in policy else None
    )

    if max_abs_increase is not None or max_rel_increase is not None:
        abs_inc = max_abs_increase if max_abs_increase is not None else float("inf")
        rel_inc = max_rel_increase if max_rel_increase is not None else 0.0
        limit = baseline + abs_inc + abs(baseline) * rel_inc
        if current > limit + eps:
            failed.append(
                {
                    "rule": "max_increase",
                    "limit": limit,
                    "max_abs_increase": abs_inc,
                    "max_rel_increase": rel_inc,
                },
            )

    enforce_reduction = baseline >= min_baseline_for_reduction and baseline > 0
    if min_abs_reduction is not None and enforce_reduction:
        if reduction + eps < min_abs_reduction:
            failed.append(
                {
                    "rule": "min_abs_reduction",
                    "required": min_abs_reduction,
                    "achieved": reduction,
                },
            )
    if min_rel_reduction is not None and enforce_reduction:
        required_rel_abs = baseline * min_rel_reduction
        if reduction + eps < required_rel_abs:
            failed.append(
                {
                    "rule": "min_rel_reduction",
                    "required_ratio": min_rel_reduction,
                    "required_abs": required_rel_abs,
                    "achieved_ratio": reduction_ratio,
                    "achieved_abs": reduction,
                },
            )
    if max_current_value is not None:
        if current > max_current_value + eps:
            failed.append(
                {
                    "rule": "max_current_value",
                    "limit": max_current_value,
                },
            )

    return {
        "scope": scope,
        "metric": metric,
        "baseline": baseline,
        "current": current,
        "delta": delta,
        "reduction": reduction,
        "reduction_ratio": reduction_ratio,
        "policy": policy,
        "passed": not failed,
        "failed_rules": failed,
    }


def _merge_policy(default_policy: dict[str, Any], override_policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = dict(default_policy)
    if override_policy:
        policy.update(override_policy)
    return policy


def _evaluate_parser_metrics(
    baseline: dict[str, Any],
    snapshot: dict[str, Any],
    thresholds: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    totals_policy = thresholds.get("totals", {})
    active_total_policy = dict(totals_policy.get("active") or {})
    all_total_policy = dict(totals_policy.get("all") or {})

    base_pi = baseline.get("parser_integrity") or {}
    base_active_total = float(base_pi.get("active_detectors_total_rows", 0) or 0)
    base_all_total = float(base_pi.get("all_detectors_total_rows", 0) or 0)

    checks.append(
        _eval_metric(
            "parser_totals",
            "active_detectors_total_rows",
            base_active_total,
            float(snapshot.get("active_total", 0) or 0),
            active_total_policy,
        ),
    )
    checks.append(
        _eval_metric(
            "parser_totals",
            "all_detectors_total_rows",
            base_all_total,
            float(snapshot.get("all_total", 0) or 0),
            all_total_policy,
        ),
    )

    base_active_map = _baseline_category_map(list(base_pi.get("active_top_categories") or []))
    curr_active_map = dict(snapshot.get("active_categories") or {})

    active_cfg = thresholds.get("active_categories") or {}
    active_default = dict(active_cfg.get("default") or {})
    active_overrides = dict(active_cfg.get("overrides") or {})

    all_active_cats = sorted(set(base_active_map) | set(curr_active_map))
    for cat in all_active_cats:
        policy = _merge_policy(active_default, active_overrides.get(cat))
        checks.append(
            _eval_metric(
                "parser_active_category",
                cat,
                float(base_active_map.get(cat, 0)),
                float(curr_active_map.get(cat, 0)),
                policy,
            ),
        )

    base_all_map = _baseline_category_map(list(base_pi.get("all_top_categories") or []))
    curr_all_map = dict(snapshot.get("all_categories") or {})
    monitor_cfg = (((thresholds.get("all_categories") or {}).get("monitor_only")) or {})
    for cat, policy in sorted(monitor_cfg.items()):
        checks.append(
            _eval_metric(
                "parser_monitor_category",
                str(cat),
                float(base_all_map.get(str(cat), 0)),
                float(curr_all_map.get(str(cat), 0)),
                dict(policy or {}),
            ),
        )

    return checks


def _compute_guardrail_metrics(db_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    clause_mod = _load_module(
        ROOT / "scripts" / "edge_case_clause_guardrail.py",
        "_clause_guardrail_mod",
    )
    parent_mod = _load_module(
        ROOT / "scripts" / "edge_case_clause_parent_guardrail.py",
        "_parent_guardrail_mod",
    )

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        clause_metrics = clause_mod._compute_clause_collision_metrics(conn)
        parent_metrics = parent_mod._compute_parent_loss_metrics(conn)
    finally:
        conn.close()
    return clause_metrics, parent_metrics


def _evaluate_guardrail_block(
    scope: str,
    current_metrics: dict[str, Any],
    baseline_payload: dict[str, Any],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    baseline_metrics = dict(baseline_payload.get("metrics") or {})
    baseline_guardrails = dict(baseline_payload.get("guardrails") or {})

    default_policy = dict(cfg.get("default") or {})
    overrides = dict(cfg.get("overrides") or {})
    metric_keys = sorted(set(baseline_guardrails.keys()) | set(overrides.keys()))

    for metric in metric_keys:
        policy = _merge_policy(default_policy, overrides.get(metric))
        checks.append(
            _eval_metric(
                scope,
                metric,
                _metric_at(baseline_metrics, metric),
                _metric_at(current_metrics, metric),
                policy,
            ),
        )
    return checks


def run_gate(
    db_path: Path,
    baseline_path: Path,
    thresholds_path: Path,
    cohort_only: bool,
) -> dict[str, Any]:
    baseline = _load_json(baseline_path)
    thresholds = _load_json(thresholds_path)

    snapshot = _fetch_parser_integrity_snapshot(db_path, cohort_only=cohort_only)
    parser_checks = _evaluate_parser_metrics(baseline, snapshot, thresholds)

    clause_metrics, parent_metrics = _compute_guardrail_metrics(db_path)

    clause_cfg = dict(thresholds.get("clause_collision_guardrail") or {})
    parent_cfg = dict(thresholds.get("parent_loss_guardrail") or {})
    clause_baseline_path = ROOT / str(
        clause_cfg.get("baseline_path", "data/quality/edge_case_clause_guardrail_baseline.json"),
    )
    parent_baseline_path = ROOT / str(
        parent_cfg.get("baseline_path", "data/quality/edge_case_clause_parent_guardrail_baseline.json"),
    )
    clause_baseline = _load_json(clause_baseline_path)
    parent_baseline = _load_json(parent_baseline_path)

    clause_checks = _evaluate_guardrail_block(
        "clause_collision_guardrail",
        clause_metrics,
        clause_baseline,
        clause_cfg,
    )
    parent_checks = _evaluate_guardrail_block(
        "parent_loss_guardrail",
        parent_metrics,
        parent_baseline,
        parent_cfg,
    )

    all_checks = [*parser_checks, *clause_checks, *parent_checks]
    failures = [check for check in all_checks if not check["passed"]]

    return {
        "ok": len(failures) == 0,
        "db": str(db_path),
        "baseline": str(baseline_path),
        "thresholds": str(thresholds_path),
        "cohort_only": cohort_only,
        "snapshot": snapshot,
        "guardrail_metrics": {
            "clause_collision": clause_metrics,
            "parent_loss": parent_metrics,
        },
        "checks": all_checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggressive parser metric gate")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--cohort-only", dest="cohort_only", action="store_true")
    parser.add_argument("--no-cohort-only", dest="cohort_only", action="store_false")
    parser.set_defaults(cohort_only=True)
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument("--report", default="", help="Optional report output path")
    args = parser.parse_args()

    report = run_gate(
        db_path=args.db,
        baseline_path=args.baseline,
        thresholds_path=args.thresholds,
        cohort_only=args.cohort_only,
    )

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        summary = {
            "ok": report["ok"],
            "failures": len(report["failures"]),
            "active_total": report["snapshot"]["active_total"],
            "all_total": report["snapshot"]["all_total"],
        }
        print(json.dumps(summary, indent=2))
        if report["failures"]:
            print("Failed metrics:")
            for fail in report["failures"]:
                print(
                    f"- [{fail['scope']}] {fail['metric']}: "
                    f"baseline={fail['baseline']}, current={fail['current']}",
                )

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
