#!/usr/bin/env python3
"""Clause parent-link regression guardrail for x/y branch parent-loss patterns.

This script computes corpus-level metrics for a specific clause parsing failure mode:
high-letter branches `(x)` / `(y)` emitted as root clauses when they likely belong
under an existing `(a)` branch in the same section.

It compares current metrics against a checked-in baseline and exits non-zero if
metrics regress beyond allowed tolerances.

Usage:
  python3 scripts/edge_case_clause_parent_guardrail.py \
    --db corpus_index/corpus.duckdb \
    --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json

To refresh baseline from current corpus snapshot:
  python3 scripts/edge_case_clause_parent_guardrail.py \
    --db corpus_index/corpus.duckdb \
    --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json \
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
    / "edge_case_clause_parent_guardrail_baseline.json"
)

REQUIRED_GUARDRAIL_PATHS: tuple[str, ...] = (
    "xy_parent_loss.docs",
    "xy_parent_loss.sections",
    "xy_parent_loss.sections_low_root_count",
    "xy_parent_loss.structural_rows",
    "xy_parent_loss.continuation_like_rows",
    "xy_parent_loss.continuation_like_ratio",
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


def _compute_parent_loss_metrics(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, float | int]]:
    row = conn.execute(
        """
        WITH depth1 AS (
          SELECT
            doc_id,
            section_number,
            lower(split_part(clause_id, '.', 1)) AS root,
            lower(coalesce(clause_text, '')) AS clause_text
          FROM clauses
          WHERE is_structural = true
            AND depth = 1
        ),
        root_counts AS (
          SELECT
            doc_id,
            section_number,
            COUNT(DISTINCT root) AS root_count
          FROM depth1
          GROUP BY 1, 2
        ),
        sec AS (
          SELECT
            d.doc_id,
            d.section_number,
            COALESCE(r.root_count, 0) AS root_count,
            bool_or(d.root = 'a') AS has_a_root,
            bool_or(d.root IN ('x', 'y')) AS has_xy_root,
            bool_or(
              d.root = 'a'
              AND regexp_matches(d.clause_text, '\\([xy]\\)')
            ) AS a_mentions_xy
          FROM depth1 d
          LEFT JOIN root_counts r USING (doc_id, section_number)
          GROUP BY 1, 2, 3
        ),
        suspicious_sections AS (
          SELECT doc_id, section_number, root_count
          FROM sec
          WHERE has_a_root
            AND has_xy_root
            AND a_mentions_xy
        ),
        suspicious_rows AS (
          SELECT
            c.doc_id,
            c.section_number,
            lower(split_part(c.clause_id, '.', 1)) AS root,
            lower(coalesce(c.clause_text, '')) AS clause_text
          FROM clauses c
          JOIN suspicious_sections s USING (doc_id, section_number)
          WHERE c.is_structural = true
            AND c.depth = 1
            AND lower(split_part(c.clause_id, '.', 1)) IN ('x', 'y')
        )
        SELECT
          COUNT(DISTINCT s.doc_id) AS docs,
          COUNT(*) AS sections,
          COUNT(*) FILTER (WHERE s.root_count <= 3) AS sections_low_root_count,
          (
            SELECT COUNT(*)
            FROM suspicious_rows
          ) AS structural_rows,
          (
            SELECT COUNT(*)
            FROM suspicious_rows
            WHERE regexp_matches(
              clause_text,
              '^\\(\\s*[xy]\\s*\\)\\s*(and|or|that|any|on|the|to|if|for|in|with|no|all|each|such|as|pursuant)\\b'
            )
          ) AS continuation_like_rows
        FROM suspicious_sections s
        """,
    ).fetchone()

    docs = int(row[0] or 0)
    sections = int(row[1] or 0)
    sections_low_root_count = int(row[2] or 0)
    structural_rows = int(row[3] or 0)
    continuation_like_rows = int(row[4] or 0)
    continuation_like_ratio = (
        float(continuation_like_rows) / float(structural_rows)
        if structural_rows > 0
        else 0.0
    )

    return {
        "xy_parent_loss": {
            "docs": docs,
            "sections": sections,
            "sections_low_root_count": sections_low_root_count,
            "structural_rows": structural_rows,
            "continuation_like_rows": continuation_like_rows,
            "continuation_like_ratio": continuation_like_ratio,
        },
    }


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
            "Clause parent-loss guardrail check. Fails if x/y parent-loss "
            "metrics regress beyond baseline tolerances."
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
        current_metrics = _compute_parent_loss_metrics(conn)
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
        print(f"Clause parent-loss guardrail status: {report['status']}")
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
