#!/usr/bin/env python3
"""Clause-collision regression guardrail for edge-case parser integrity.

This script computes clause-collision metrics from corpus DuckDB and compares
them against a checked-in baseline. It exits non-zero if any guarded metric
regresses beyond allowed tolerances.

Usage:
  python3 scripts/edge_case_clause_guardrail.py \
    --db corpus_index/corpus.duckdb \
    --baseline data/quality/edge_case_clause_guardrail_baseline.json

To refresh baseline from current corpus snapshot:
  python3 scripts/edge_case_clause_guardrail.py \
    --db corpus_index/corpus.duckdb \
    --baseline data/quality/edge_case_clause_guardrail_baseline.json \
    --write-baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

try:
    import orjson

    def _dump_json(obj: object) -> bytes:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)

    def _load_json(data: bytes) -> Any:
        return orjson.loads(data)
except ImportError:

    def _dump_json(obj: object) -> bytes:
        return json.dumps(obj, indent=2, sort_keys=True, default=str).encode("utf-8")

    def _load_json(data: bytes) -> Any:
        return json.loads(data)


DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "quality"
    / "edge_case_clause_guardrail_baseline.json"
)

REQUIRED_GUARDRAIL_PATHS: tuple[str, ...] = (
    "clause_dup_id_burst.docs",
    "clause_dup_id_burst.max_dup_ratio",
    "clause_root_label_repeat_explosion.docs",
    "clause_root_label_repeat_explosion.max_repeat",
    "clause_depth_reset_after_deep.docs",
    "clause_depth_reset_after_deep.total_resets",
)


def _metric_at(metrics: dict[str, Any], dotted: str) -> float:
    parts = dotted.split(".")
    value: Any = metrics
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return float(value)


def _default_guardrails() -> dict[str, dict[str, float]]:
    return {
        path: {"max_abs_increase": 0.0, "max_rel_increase": 0.0}
        for path in REQUIRED_GUARDRAIL_PATHS
    }


def _compute_clause_collision_metrics(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, float | int]]:
    metrics: dict[str, dict[str, float | int]] = {}

    dup_row = conn.execute(
        """
        WITH per_doc AS (
          SELECT
            doc_id,
            COUNT(*) FILTER (WHERE is_structural = true) AS structural_count,
            1.0 * SUM(CASE
              WHEN is_structural = true AND clause_id LIKE '%\\_dup%' ESCAPE '\\'
              THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*) FILTER (WHERE is_structural = true), 0) AS dup_ratio
          FROM clauses
          GROUP BY doc_id
        ), flagged AS (
          SELECT * FROM per_doc
          WHERE structural_count >= 200 AND dup_ratio > 0.90
        )
        SELECT
          COUNT(*) AS docs,
          COALESCE(MAX(dup_ratio), 0),
          COALESCE(AVG(dup_ratio), 0),
          COALESCE(quantile_cont(dup_ratio, 0.95), 0)
        FROM flagged
        """,
    ).fetchone()
    metrics["clause_dup_id_burst"] = {
        "docs": int(dup_row[0] or 0),
        "max_dup_ratio": float(dup_row[1] or 0.0),
        "avg_dup_ratio": float(dup_row[2] or 0.0),
        "p95_dup_ratio": float(dup_row[3] or 0.0),
    }

    root_repeat_row = conn.execute(
        """
        WITH root_counts AS (
          SELECT
            doc_id,
            section_number,
            lower(regexp_extract(label, '\\(([A-Za-z0-9]+)\\)', 1)) AS root_lbl,
            COUNT(*) AS n
          FROM clauses
          WHERE is_structural = true
            AND array_length(string_split(clause_id, '.')) = 1
            AND regexp_extract(label, '\\(([A-Za-z0-9]+)\\)', 1) <> ''
          GROUP BY 1, 2, 3
        ), sec AS (
          SELECT doc_id, section_number, MAX(n) AS max_repeat
          FROM root_counts
          GROUP BY 1, 2
        ), flagged AS (
          SELECT * FROM sec WHERE max_repeat >= 200
        )
        SELECT
          COUNT(DISTINCT doc_id) AS docs,
          COALESCE(MAX(max_repeat), 0) AS max_repeat,
          COALESCE(AVG(max_repeat), 0) AS avg_repeat,
          COALESCE(quantile_cont(max_repeat, 0.95), 0) AS p95_repeat
        FROM flagged
        """,
    ).fetchone()
    metrics["clause_root_label_repeat_explosion"] = {
        "docs": int(root_repeat_row[0] or 0),
        "max_repeat": float(root_repeat_row[1] or 0.0),
        "avg_repeat": float(root_repeat_row[2] or 0.0),
        "p95_repeat": float(root_repeat_row[3] or 0.0),
    }

    depth_reset_row = conn.execute(
        """
        WITH ordered AS (
          SELECT
            doc_id,
            section_number,
            span_start,
            array_length(string_split(clause_id, '.')) as tree_level,
            lower(regexp_extract(label, '\\(([A-Za-z0-9]+)\\)', 1)) as label_inner,
            lag(array_length(string_split(clause_id, '.')))
              OVER (PARTITION BY doc_id, section_number ORDER BY span_start)
              as prev_tree_level
          FROM clauses
          WHERE is_structural = true
        ), sec AS (
          SELECT doc_id, section_number, COUNT(*) AS reset_count
          FROM ordered
          WHERE prev_tree_level >= 4
            AND tree_level = 1
            AND length(label_inner) = 1
            AND label_inner BETWEEN 'm' AND 'z'
          GROUP BY 1, 2
          HAVING COUNT(*) >= 2
        ), doc AS (
          SELECT
            doc_id,
            COUNT(*) AS flagged_sections,
            SUM(reset_count) AS total_resets
          FROM sec
          GROUP BY 1
        )
        SELECT
          COUNT(*) AS docs,
          COALESCE(SUM(flagged_sections), 0) AS flagged_sections,
          COALESCE(SUM(total_resets), 0) AS total_resets,
          COALESCE(MAX(total_resets), 0) AS max_resets_per_doc
        FROM doc
        """,
    ).fetchone()
    metrics["clause_depth_reset_after_deep"] = {
        "docs": int(depth_reset_row[0] or 0),
        "flagged_sections_total": int(depth_reset_row[1] or 0),
        "total_resets": int(depth_reset_row[2] or 0),
        "max_resets_per_doc": int(depth_reset_row[3] or 0),
    }

    return metrics


def _evaluate_guardrails(
    current: dict[str, Any],
    baseline_metrics: dict[str, Any],
    guardrails: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    eps = 1e-12

    for metric_path in REQUIRED_GUARDRAIL_PATHS:
        policy = guardrails.get(metric_path, {})
        max_abs_increase = float(policy.get("max_abs_increase", 0.0) or 0.0)
        max_rel_increase = float(policy.get("max_rel_increase", 0.0) or 0.0)

        try:
            current_value = _metric_at(current, metric_path)
            baseline_value = _metric_at(baseline_metrics, metric_path)
        except KeyError:
            failures.append(
                {
                    "metric": metric_path,
                    "reason": "missing_metric",
                    "current": None,
                    "baseline": None,
                    "limit": None,
                },
            )
            continue

        limit = baseline_value + max_abs_increase + abs(baseline_value) * max_rel_increase
        passed = current_value <= limit + eps
        check = {
            "metric": metric_path,
            "current": current_value,
            "baseline": baseline_value,
            "limit": limit,
            "max_abs_increase": max_abs_increase,
            "max_rel_increase": max_rel_increase,
            "passed": passed,
        }
        checks.append(check)
        if not passed:
            failures.append(
                {
                    "metric": metric_path,
                    "reason": "regression",
                    "current": current_value,
                    "baseline": baseline_value,
                    "limit": limit,
                },
            )

    return {
        "status": "pass" if not failures else "fail",
        "checks": checks,
        "failures": failures,
    }


def _write_baseline(
    path: Path,
    db_path: Path,
    metrics: dict[str, Any],
    guardrails: dict[str, Any] | None = None,
) -> None:
    payload = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_db": str(db_path),
        "metrics": metrics,
        "guardrails": guardrails or _default_guardrails(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_dump_json(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clause-collision guardrail check. Fails if "
            "edge-case collision metrics regress beyond baseline tolerances."
        ),
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("corpus_index/corpus.duckdb"),
        help="Path to corpus DuckDB (default: corpus_index/corpus.duckdb)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Baseline JSON path",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write baseline file from current metrics and exit",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON report",
    )
    args = parser.parse_args(argv)

    try:
        conn = duckdb.connect(str(args.db), read_only=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to open DuckDB: {args.db} ({exc})", file=sys.stderr)
        return 2

    try:
        current_metrics = _compute_clause_collision_metrics(conn)
    finally:
        conn.close()

    if args.write_baseline:
        _write_baseline(args.baseline, args.db, current_metrics, _default_guardrails())
        print(f"Wrote baseline: {args.baseline}")
        return 0

    if not args.baseline.exists():
        print(
            (
                f"Baseline file not found: {args.baseline}. "
                "Run with --write-baseline first."
            ),
            file=sys.stderr,
        )
        return 2

    payload = _load_json(args.baseline.read_bytes())
    baseline_metrics = dict(payload.get("metrics") or {})
    guardrails = dict(payload.get("guardrails") or _default_guardrails())

    evaluation = _evaluate_guardrails(current_metrics, baseline_metrics, guardrails)
    report = {
        "status": evaluation["status"],
        "db": str(args.db),
        "baseline": str(args.baseline),
        "current_metrics": current_metrics,
        "checks": evaluation["checks"],
        "failures": evaluation["failures"],
    }

    if args.json:
        print(_dump_json(report).decode("utf-8"))
    else:
        print(f"Clause guardrail status: {report['status']}")
        for check in report["checks"]:
            mark = "PASS" if check["passed"] else "FAIL"
            print(
                f"- [{mark}] {check['metric']}: "
                f"current={check['current']} limit={check['limit']} "
                f"(baseline={check['baseline']})",
            )
        if report["failures"]:
            print("Regressions detected:")
            for failure in report["failures"]:
                print(
                    f"  - {failure['metric']}: "
                    f"{failure['current']} > {failure['limit']} "
                    f"(baseline {failure['baseline']})",
                )

    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
