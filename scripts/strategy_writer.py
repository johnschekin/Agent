#!/usr/bin/env python3
"""Persist strategy with versioning + regression circuit breaker.

Usage:
    python3 scripts/strategy_writer.py \\
      --concept-id debt_capacity.indebtedness \\
      --workspace workspaces/indebtedness \\
      --strategy updated.json \\
      --note "Added Cahill heading variant" \\
      --db corpus_index/corpus.duckdb

Outputs structured JSON to stdout, human messages to stderr.
"""

import argparse
import contextlib
import glob
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.corpus import SchemaVersionError, ensure_schema_version
from agent.strategy import normalize_template_overrides, resolve_strategy_dict

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def load_json(path: Path) -> object:
        return orjson.loads(path.read_bytes())

    def write_json(path: Path, obj: object) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def load_json(path: Path) -> object:
        with open(path) as f:
            return json.load(f)

    def write_json(path: Path, obj: object) -> None:
        with open(path, "w") as f:
            json.dump(obj, f, indent=2, default=str)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _update_workspace_checkpoint_after_save(
    workspace: Path,
    *,
    concept_id: str,
    strategy_path: Path,
    version: int,
) -> dict[str, Any]:
    checkpoint_path = workspace / "checkpoint.json"
    payload: dict[str, Any] = {}
    if checkpoint_path.exists():
        with contextlib.suppress(Exception):
            loaded = load_json(checkpoint_path)
            if isinstance(loaded, dict):
                payload = dict(loaded)

    status = str(payload.get("status", "")).strip().lower()
    if status not in {"completed", "locked"}:
        status = "running"

    payload["family"] = str(payload.get("family") or workspace.name)
    payload["status"] = status
    payload["iteration_count"] = _as_int(payload.get("iteration_count"), 0) + 1
    payload["last_strategy_version"] = int(version)
    payload["last_saved_strategy_file"] = str(strategy_path)
    payload["current_concept_id"] = concept_id
    payload["last_concept_id"] = concept_id
    payload["last_saved_at"] = datetime.now(UTC).isoformat()
    payload["last_update"] = payload["last_saved_at"]

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(checkpoint_path, payload)
    return {
        "path": str(checkpoint_path),
        "status": str(payload.get("status", "")),
        "iteration_count": int(payload.get("iteration_count", 0)),
        "last_strategy_version": int(payload.get("last_strategy_version", 0)),
    }


def _parse_concept_whitelist(raw: str | None) -> tuple[set[str], tuple[str, ...]]:
    """Parse whitelist entries into exact concept IDs and subtree prefixes.

    Supported entries:
    - exact: `debt_capacity.indebtedness`
    - subtree wildcard: `debt_capacity.indebtedness.*`
    """
    if not raw:
        return set(), ()
    exact: set[str] = set()
    prefixes: set[str] = set()
    for part in str(raw).split(","):
        val = part.strip()
        if not val:
            continue
        if val.endswith(".*"):
            prefix = val[:-2].strip()
            if prefix:
                prefixes.add(prefix)
            continue
        if val.endswith("*"):
            prefix = val[:-1].strip().rstrip(".")
            if prefix:
                prefixes.add(prefix)
            continue
        exact.add(val)
    return exact, tuple(sorted(prefixes))


def _concept_allowed(
    concept_id: str,
    *,
    exact: set[str],
    prefixes: tuple[str, ...],
) -> bool:
    if concept_id in exact:
        return True
    for prefix in prefixes:
        if concept_id == prefix or concept_id.startswith(prefix + "."):
            return True
    return False


def _extract_strategy_concept_ids(payload: object) -> set[str]:
    ids: set[str] = set()
    if not isinstance(payload, dict):
        return ids
    concept_id = str(payload.get("concept_id", "")).strip()
    if concept_id:
        ids.add(concept_id)

    for key in ("out_of_scope_discoveries", "discovered_concepts"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    ids.add(text)
            elif isinstance(item, dict):
                cid = str(item.get("concept_id", "")).strip()
                if cid:
                    ids.add(cid)
    return ids


def _append_out_of_scope_log(
    log_path: Path,
    *,
    actor: str,
    concept_id: str,
    source: str,
    reason: str,
    strategy_path: Path,
) -> None:
    row = {
        "schema_version": "out_of_scope_discovery_v1",
        "created_at": datetime.now(UTC).isoformat(),
        "actor": actor,
        "concept_id": concept_id,
        "source": source,
        "reason": reason,
        "strategy_path": str(strategy_path),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as f:
        f.write((json.dumps(row) + "\n").encode("utf-8"))


def _view_paths(strategies_dir: Path, concept_id: str, version_str: str) -> tuple[Path, Path]:
    """Companion files for raw/resolved strategy views."""
    raw_path = strategies_dir / f"{concept_id}_{version_str}.raw.json"
    resolved_path = strategies_dir / f"{concept_id}_{version_str}.resolved.json"
    return raw_path, resolved_path


def find_latest_version(strategies_dir: Path, concept_id: str) -> tuple[int, Path | None]:
    """Find the latest version number and path for a concept's strategy."""
    pattern = str(strategies_dir / f"{concept_id}_v*.json")
    files = glob.glob(pattern)

    if not files:
        return 0, None

    max_version = 0
    max_path: Path | None = None

    for f in files:
        match = re.search(r"_v(\d+)\.json$", f)
        if match:
            version = int(match.group(1))
            if version > max_version:
                max_version = version
                max_path = Path(f)

    return max_version, max_path


def run_strategy_against_docs(
    strategy: object, con: object, concept_id: str, *, cohort_only: bool = True
) -> dict[str, dict]:
    """Run a strategy against all docs and return hit rates grouped by template_family.

    Returns: {group_name: {"hits": int, "total": int, "hit_rate": float}}
    """
    import duckdb

    assert isinstance(con, duckdb.DuckDBPyConnection)

    # Discover tables
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]

    # Find documents table
    docs_table = None
    for candidate in ["documents", "docs", "document", "metadata"]:
        if candidate in tables:
            docs_table = candidate
            break

    if not docs_table:
        log("Warning: no documents table found for regression test")
        return {}

    columns_info = con.execute(
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{docs_table}'"
    ).fetchall()
    columns = [row[0] for row in columns_info]

    doc_id_col = next(
        (c for c in columns if c in ("doc_id", "document_id", "id")), None
    )
    family_col = next(
        (c for c in columns if c in ("template_family", "family", "firm", "law_firm")),
        None,
    )
    text_col = next(
        (c for c in columns if c in ("text", "content", "body", "full_text")), None
    )

    if not doc_id_col:
        log("Warning: no doc_id column found in documents table")
        return {}

    cohort_clause = ""
    if cohort_only and "cohort_included" in columns:
        cohort_clause = " WHERE d.cohort_included = true"

    # Build (doc_id, group, doc_text) rows for regression evaluation.
    # Prefer section_text aggregation when present, because the documents table is
    # metadata-only in the Agent schema and does not contain full text.
    if "section_text" in tables:
        if family_col:
            rows = con.execute(
                f"""
                SELECT
                    d.{doc_id_col} AS doc_id,
                    d.{family_col} AS template_family,
                    COALESCE(
                        string_agg(st.text, '\n' ORDER BY st.section_number),
                        ''
                    ) AS doc_text
                FROM {docs_table} d
                LEFT JOIN section_text st
                    ON st.doc_id = d.{doc_id_col}
                {cohort_clause}
                GROUP BY d.{doc_id_col}, d.{family_col}
                """
            ).fetchall()
        else:
            rows = con.execute(
                f"""
                SELECT
                    d.{doc_id_col} AS doc_id,
                    'all' AS template_family,
                    COALESCE(
                        string_agg(st.text, '\n' ORDER BY st.section_number),
                        ''
                    ) AS doc_text
                FROM {docs_table} d
                LEFT JOIN section_text st
                    ON st.doc_id = d.{doc_id_col}
                {cohort_clause}
                GROUP BY d.{doc_id_col}
                """
            ).fetchall()
    elif text_col:
        where_clause = (
            " WHERE cohort_included = true"
            if cohort_only and "cohort_included" in columns
            else ""
        )
        if family_col:
            rows = con.execute(
                "SELECT "
                f"{doc_id_col}, {family_col}, COALESCE({text_col}, '') "
                f"FROM {docs_table}{where_clause}"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT "
                f"{doc_id_col}, 'all', COALESCE({text_col}, '') "
                f"FROM {docs_table}{where_clause}"
            ).fetchall()
    else:
        log(
            "Warning: no text source found for regression test "
            "(expected section_text table or text column)"
        )
        return {}

    # Extract patterns from strategy
    if not isinstance(strategy, dict):
        log("Warning: strategy is not a dict, cannot run regression")
        return {}

    patterns: list[re.Pattern] = []
    strategy_patterns = strategy.get("patterns", [])
    if isinstance(strategy_patterns, list):
        for p in strategy_patterns:
            if isinstance(p, str):
                with contextlib.suppress(re.error):
                    patterns.append(re.compile(p, re.IGNORECASE))
            elif isinstance(p, dict):
                pat_str = p.get("pattern", p.get("regex", ""))
                if pat_str:
                    with contextlib.suppress(re.error):
                        flags = re.IGNORECASE
                        if p.get("multiline"):
                            flags |= re.MULTILINE
                        patterns.append(re.compile(pat_str, flags))

    # Also check common strategy phrase fields.
    for key in (
        "heading_patterns",
        "keyword_patterns",
        "keyword_anchors",
        "keyword_anchors_section_only",
        "concept_specific_keywords",
        "dna_tier1",
        "dna_tier2",
        "regexes",
    ):
        extra = strategy.get(key, [])
        if isinstance(extra, list):
            for p in extra:
                pat_str = (
                    p
                    if isinstance(p, str)
                    else (p.get("pattern", "") if isinstance(p, dict) else "")
                )
                if pat_str:
                    with contextlib.suppress(re.error):
                        patterns.append(re.compile(pat_str, re.IGNORECASE))

    if not patterns:
        log("Warning: no valid patterns found in strategy")
        return {}

    # Run patterns against docs
    groups: dict[str, dict] = {}

    for row in rows:
        group = row[1] if len(row) > 1 else "all"
        doc_text = row[2] if len(row) > 2 else ""

        if group is None:
            group = "unknown"

        if group not in groups:
            groups[group] = {"hits": 0, "total": 0, "hit_rate": 0.0}

        groups[group]["total"] += 1

        if doc_text:
            hit = any(p.search(doc_text) for p in patterns)
            if hit:
                groups[group]["hits"] += 1

    # Calculate hit rates
    for g in groups.values():
        if g["total"] > 0:
            g["hit_rate"] = round(g["hits"] / g["total"], 4)

    return groups


def validate_regression_results(
    old_results: dict[str, dict],
    new_results: dict[str, dict],
) -> tuple[bool, str]:
    """Validate regression evaluation outputs before applying circuit breaker.

    Rejects strategy updates when evaluation produced no usable groups, which
    typically means no valid patterns were compiled or no text source was
    available. Without this guard, an empty evaluation can silently pass.
    """
    if not old_results:
        return False, "Current strategy produced no evaluable regression groups."
    if not new_results:
        return False, "Updated strategy produced no evaluable regression groups."

    old_total = sum(int(g.get("total", 0)) for g in old_results.values())
    new_total = sum(int(g.get("total", 0)) for g in new_results.values())
    if old_total <= 0:
        return False, "Current strategy regression set has zero evaluated documents."
    if new_total <= 0:
        return False, "Updated strategy regression set has zero evaluated documents."

    return True, ""


def _to_float(value: Any, *, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def evaluate_template_stability_policy(
    results: dict[str, dict],
    policy: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """Evaluate template-group stability requirements against grouped hit rates."""
    if not policy:
        return True, "", {"enforced": False}

    min_group_size = max(1, _to_int(policy.get("min_group_size"), default=10))
    min_groups = max(1, _to_int(policy.get("min_groups"), default=2))
    min_group_hit_rate = _to_float(policy.get("min_group_hit_rate"), default=None)
    max_group_hit_rate_gap = _to_float(policy.get("max_group_hit_rate_gap"), default=None)
    max_single_group_doc_share = _to_float(policy.get("max_single_group_doc_share"), default=None)
    max_single_group_hit_share = _to_float(policy.get("max_single_group_hit_share"), default=None)

    eligible = {
        group: payload
        for group, payload in results.items()
        if _to_int(payload.get("total"), default=0) >= min_group_size
    }
    details: dict[str, Any] = {
        "enforced": True,
        "policy": {
            "min_group_size": min_group_size,
            "min_groups": min_groups,
            "min_group_hit_rate": min_group_hit_rate,
            "max_group_hit_rate_gap": max_group_hit_rate_gap,
            "max_single_group_doc_share": max_single_group_doc_share,
            "max_single_group_hit_share": max_single_group_hit_share,
        },
        "eligible_groups": sorted(eligible.keys()),
    }

    if len(eligible) < min_groups:
        reason = (
            f"Template stability gate failed: only {len(eligible)} template groups "
            f"meet min_group_size={min_group_size} (required {min_groups})."
        )
        details["reason"] = reason
        return False, reason, details

    low_groups: list[dict[str, Any]] = []
    rates: list[float] = []
    total_docs = 0
    total_hits = 0
    max_docs_group = ("", 0)
    max_hits_group = ("", 0)

    for group, payload in eligible.items():
        hit_rate = _to_float(payload.get("hit_rate"), default=0.0) or 0.0
        total = _to_int(payload.get("total"), default=0)
        hits = _to_int(payload.get("hits"), default=0)
        rates.append(hit_rate)
        total_docs += total
        total_hits += hits
        if total > max_docs_group[1]:
            max_docs_group = (group, total)
        if hits > max_hits_group[1]:
            max_hits_group = (group, hits)
        if min_group_hit_rate is not None and hit_rate < min_group_hit_rate:
            low_groups.append(
                {"group": group, "hit_rate": round(hit_rate, 4), "total": total}
            )

    details["min_group_hit_rate_failures"] = low_groups

    if low_groups:
        reason = (
            "Template stability gate failed: one or more template groups are below "
            f"min_group_hit_rate={min_group_hit_rate}."
        )
        details["reason"] = reason
        return False, reason, details

    if rates and max_group_hit_rate_gap is not None:
        spread = max(rates) - min(rates)
        details["group_hit_rate_gap"] = round(spread, 4)
        if spread > max_group_hit_rate_gap:
            reason = (
                "Template stability gate failed: group hit-rate gap "
                f"{spread:.4f} exceeds max_group_hit_rate_gap={max_group_hit_rate_gap:.4f}."
            )
            details["reason"] = reason
            return False, reason, details

    if total_docs > 0:
        top_doc_share = max_docs_group[1] / total_docs
        details["top_doc_share"] = round(top_doc_share, 4)
        details["top_doc_group"] = max_docs_group[0]
        if (
            max_single_group_doc_share is not None
            and top_doc_share > max_single_group_doc_share
        ):
            reason = (
                "Template stability gate failed: top document share "
                f"{top_doc_share:.4f} exceeds "
                "max_single_group_doc_share="
                f"{max_single_group_doc_share:.4f}."
            )
            details["reason"] = reason
            return False, reason, details

    if total_hits > 0:
        top_hit_share = max_hits_group[1] / total_hits
        details["top_hit_share"] = round(top_hit_share, 4)
        details["top_hit_group"] = max_hits_group[0]
        if (
            max_single_group_hit_share is not None
            and top_hit_share > max_single_group_hit_share
        ):
            reason = (
                "Template stability gate failed: top hit share "
                f"{top_hit_share:.4f} exceeds "
                "max_single_group_hit_share="
                f"{max_single_group_hit_share:.4f}."
            )
            details["reason"] = reason
            return False, reason, details

    return True, "", details


def evaluate_outlier_summary_against_policy(
    outlier_summary: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """Evaluate outlier summary metrics against policy limits."""
    metrics = {
        "outlier_rate": _to_float(outlier_summary.get("outlier_rate"), default=0.0) or 0.0,
        "high_risk_rate": _to_float(outlier_summary.get("high_risk_rate"), default=0.0) or 0.0,
        "review_risk_rate": _to_float(outlier_summary.get("review_risk_rate"), default=0.0) or 0.0,
    }
    limits = {
        "max_outlier_rate": _to_float(policy.get("max_outlier_rate"), default=None),
        "max_high_risk_rate": _to_float(policy.get("max_high_risk_rate"), default=None),
        "max_review_rate": _to_float(policy.get("max_review_rate"), default=None),
    }
    limits = {k: v for k, v in limits.items() if v is not None}

    checks = {
        "max_outlier_rate": ("outlier_rate", limits.get("max_outlier_rate")),
        "max_high_risk_rate": ("high_risk_rate", limits.get("max_high_risk_rate")),
        "max_review_rate": ("review_risk_rate", limits.get("max_review_rate")),
    }
    violations: list[dict[str, Any]] = []
    for limit_name, (metric_name, limit_value) in checks.items():
        if limit_value is None:
            continue
        metric_value = metrics[metric_name]
        if metric_value > limit_value:
            violations.append(
                {
                    "metric": metric_name,
                    "value": round(metric_value, 4),
                    "limit": round(limit_value, 4),
                    "limit_name": limit_name,
                }
            )

    details = {
        "metrics": metrics,
        "limits": limits,
        "violations": violations,
        "evaluated_hits": _to_int(outlier_summary.get("evaluated_hits"), default=0),
        "thresholds": outlier_summary.get("thresholds", {}),
    }
    if not violations:
        return True, "", details

    first = violations[0]
    reason = (
        "Outlier policy gate failed: "
        f"{first['metric']}={first['value']:.4f} exceeds limit {first['limit']:.4f}."
    )
    return False, reason, details


def evaluate_did_not_find_summary_against_policy(
    did_not_find_summary: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """Evaluate did_not_find summary metrics against policy limits."""
    metrics = {
        "coverage": _to_float(did_not_find_summary.get("coverage"), default=0.0) or 0.0,
        "near_miss_rate": (
            _to_float(did_not_find_summary.get("near_miss_rate"), default=0.0) or 0.0
        ),
        "near_miss_count": _to_int(did_not_find_summary.get("near_miss_count"), default=0),
    }
    limits = {
        "min_coverage": _to_float(policy.get("min_coverage"), default=None),
        "max_near_miss_rate": _to_float(policy.get("max_near_miss_rate"), default=None),
        "max_near_miss_count": _to_int(policy.get("max_near_miss_count"), default=-1),
    }
    if limits["max_near_miss_count"] is not None and limits["max_near_miss_count"] < 0:
        limits["max_near_miss_count"] = None

    violations: list[dict[str, Any]] = []
    min_coverage = limits.get("min_coverage")
    if min_coverage is not None and metrics["coverage"] < min_coverage:
        violations.append(
            {
                "metric": "coverage",
                "value": round(metrics["coverage"], 4),
                "limit": round(min_coverage, 4),
                "limit_name": "min_coverage",
            }
        )

    max_near_miss_rate = limits.get("max_near_miss_rate")
    if max_near_miss_rate is not None and metrics["near_miss_rate"] > max_near_miss_rate:
        violations.append(
            {
                "metric": "near_miss_rate",
                "value": round(metrics["near_miss_rate"], 4),
                "limit": round(max_near_miss_rate, 4),
                "limit_name": "max_near_miss_rate",
            }
        )

    max_near_miss_count = limits.get("max_near_miss_count")
    if max_near_miss_count is not None and metrics["near_miss_count"] > max_near_miss_count:
        violations.append(
            {
                "metric": "near_miss_count",
                "value": metrics["near_miss_count"],
                "limit": max_near_miss_count,
                "limit_name": "max_near_miss_count",
            }
        )

    details = {
        "metrics": metrics,
        "limits": {k: v for k, v in limits.items() if v is not None},
        "violations": violations,
        "near_miss_cutoff": _to_float(
            did_not_find_summary.get("near_miss_cutoff"),
            default=0.0,
        )
        or 0.0,
        "passes_policy": bool(did_not_find_summary.get("passes_policy", True)),
        "source_summary": did_not_find_summary,
    }
    if not violations:
        return True, "", details

    first = violations[0]
    comparator = "<" if first["limit_name"] == "min_coverage" else ">"
    reason = (
        "Did-not-find policy gate failed: "
        f"{first['metric']}={first['value']} {comparator} limit {first['limit']}."
    )
    return False, reason, details


def evaluate_confidence_summary_against_policy(
    hit_summary: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """Evaluate confidence distribution constraints from pattern_tester output."""
    confidence_dist = hit_summary.get("confidence_distribution", {})
    if not isinstance(confidence_dist, dict):
        confidence_dist = {}

    high = _to_int(confidence_dist.get("high"), default=0)
    medium = _to_int(confidence_dist.get("medium"), default=0)
    low = _to_int(confidence_dist.get("low"), default=0)
    total = max(0, high + medium + low)

    high_rate = (high / total) if total else 0.0
    low_rate = (low / total) if total else 0.0

    min_high_rate = _to_float(policy.get("min_high_confidence_rate"), default=None)
    max_low_rate = _to_float(policy.get("max_low_confidence_rate"), default=None)

    violations: list[dict[str, Any]] = []
    if min_high_rate is not None and high_rate < min_high_rate:
        violations.append(
            {
                "metric": "high_confidence_rate",
                "value": round(high_rate, 4),
                "limit": min_high_rate,
                "limit_name": "min_high_confidence_rate",
            }
        )
    if max_low_rate is not None and low_rate > max_low_rate:
        violations.append(
            {
                "metric": "low_confidence_rate",
                "value": round(low_rate, 4),
                "limit": max_low_rate,
                "limit_name": "max_low_confidence_rate",
            }
        )

    details = {
        "metrics": {
            "high_confidence_count": high,
            "medium_confidence_count": medium,
            "low_confidence_count": low,
            "high_confidence_rate": round(high_rate, 4),
            "low_confidence_rate": round(low_rate, 4),
            "evaluated_hits": total,
        },
        "limits": {
            key: val
            for key, val in {
                "min_high_confidence_rate": min_high_rate,
                "max_low_confidence_rate": max_low_rate,
            }.items()
            if val is not None
        },
        "violations": violations,
    }
    if not violations:
        return True, "", details

    first = violations[0]
    comparator = "<" if first["limit_name"] == "min_high_confidence_rate" else ">"
    reason = (
        "Confidence policy gate failed: "
        f"{first['metric']}={first['value']} {comparator} limit {first['limit']}."
    )
    return False, reason, details


def run_outlier_policy_probe(
    strategy_path: Path,
    db_path: Path,
    outlier_policy: dict[str, Any],
    did_not_find_policy: dict[str, Any],
    confidence_policy: dict[str, Any],
    *,
    include_all: bool,
) -> tuple[bool, str, dict[str, Any]]:
    """Run pattern_tester probe and enforce outlier/did-not-find policy limits."""
    sample_size = max(25, _to_int(outlier_policy.get("sample_size"), default=200))
    cmd = [
        sys.executable,
        str(Path(__file__).with_name("pattern_tester.py")),
        "--db",
        str(db_path),
        "--strategy",
        str(strategy_path),
        "--sample",
        str(sample_size),
    ]
    if include_all:
        cmd.append("--include-all")
    if bool(outlier_policy.get("no_strict_keyword_gate", False)):
        cmd.append("--no-strict-keyword-gate")
    if "hit_threshold" in outlier_policy:
        cmd.extend(["--hit-threshold", str(outlier_policy["hit_threshold"])])
    if "min_keyword_hits" in outlier_policy:
        cmd.extend(["--min-keyword-hits", str(outlier_policy["min_keyword_hits"])])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        reason = "Outlier policy probe failed (pattern_tester returned non-zero)."
        details = {
            "cmd": cmd,
            "returncode": result.returncode,
            "stderr_tail": result.stderr.strip().splitlines()[-20:],
            "stdout_tail": result.stdout.strip().splitlines()[-20:],
        }
        return False, reason, details

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        reason = "Outlier policy probe failed: invalid JSON from pattern_tester."
        details = {
            "cmd": cmd,
            "stdout_head": (result.stdout or "")[:2000],
            "stderr_tail": result.stderr.strip().splitlines()[-20:],
        }
        return False, reason, details

    outlier_summary = payload.get("outlier_summary")
    if not isinstance(outlier_summary, dict):
        return False, "Outlier policy probe failed: missing outlier_summary.", {"cmd": cmd}

    ok, reason, details = evaluate_outlier_summary_against_policy(outlier_summary, outlier_policy)
    details["sample_size"] = sample_size
    details["hit_rate"] = _to_float(payload.get("hit_rate"), default=0.0) or 0.0
    details["total_docs"] = _to_int(payload.get("total_docs"), default=0)
    hit_summary = payload.get("hit_summary")
    if not isinstance(hit_summary, dict):
        hit_summary = {}
    details["hit_summary"] = hit_summary

    did_details: dict[str, Any] = {"enforced": False}
    if did_not_find_policy:
        did_not_find_summary = payload.get("did_not_find_summary")
        if not isinstance(did_not_find_summary, dict):
            return (
                False,
                "Did-not-find policy probe failed: missing did_not_find_summary.",
                {
                    "sample_size": sample_size,
                    "cmd": cmd,
                },
            )
        did_ok, did_reason, did_details = evaluate_did_not_find_summary_against_policy(
            did_not_find_summary,
            did_not_find_policy,
        )
        did_details["enforced"] = True
        details["did_not_find_policy"] = did_details
        if not did_ok:
            return False, did_reason, details

    conf_details: dict[str, Any] = {"enforced": False}
    if confidence_policy:
        conf_ok, conf_reason, conf_details = evaluate_confidence_summary_against_policy(
            hit_summary,
            confidence_policy,
        )
        conf_details["enforced"] = True
        details["confidence_policy"] = conf_details
        if not conf_ok:
            return False, conf_reason, details

    if "did_not_find_policy" not in details:
        details["did_not_find_policy"] = did_details
    if "confidence_policy" not in details:
        details["confidence_policy"] = conf_details
    return ok, reason, details


def ensure_strategy_v2_gates(strategy: dict[str, Any]) -> tuple[bool, str]:
    """Ensure Strategy v2 policies are defined before saving."""
    if strategy.get("acceptance_policy_version", "v1") != "v2":
        return True, ""

    for field in (
        "outlier_policy",
        "template_stability_policy",
        "did_not_find_policy",
    ):
        value = strategy.get(field)
        if not isinstance(value, dict):
            return False, f"Strategy v2 requires {field} to be a dictionary."
        if not value:
            return False, f"Strategy v2 requires {field} to define at least one threshold."

    return True, ""


def evaluate_llm_judge_report(
    report: dict[str, Any],
    *,
    concept_id: str,
    min_precision: float,
    min_samples: int,
    precision_mode: str = "strict",
) -> tuple[bool, str, dict[str, Any]]:
    """Validate llm_judge output for release-mode strategy promotion."""
    reported_concept = str(report.get("concept_id", "") or "")
    if reported_concept and reported_concept != concept_id:
        reason = (
            "LLM judge report concept mismatch: "
            f"expected {concept_id}, got {reported_concept}."
        )
        return False, reason, {"reported_concept_id": reported_concept}

    n_sampled = _to_int(report.get("n_sampled"), default=0)
    strict_precision = _to_float(report.get("precision_estimate"), default=None)
    weighted_precision = _to_float(report.get("weighted_precision_estimate"), default=None)
    if strict_precision is None:
        strict_precision = 0.0
    if weighted_precision is None:
        weighted_precision = strict_precision

    selected_precision = strict_precision
    precision_field = "precision_estimate"
    if precision_mode == "weighted":
        selected_precision = weighted_precision
        precision_field = "weighted_precision_estimate"

    details: dict[str, Any] = {
        "schema_version": str(report.get("schema_version", "")),
        "concept_id": concept_id,
        "reported_concept_id": reported_concept,
        "n_sampled": n_sampled,
        "min_samples": min_samples,
        "precision_mode": precision_mode,
        "selected_precision_field": precision_field,
        "selected_precision": round(selected_precision, 4),
        "min_precision": round(min_precision, 4),
        "strict_precision": round(strict_precision, 4),
        "weighted_precision": round(weighted_precision, 4),
        "correct": _to_int(report.get("correct"), default=0),
        "partial": _to_int(report.get("partial"), default=0),
        "wrong": _to_int(report.get("wrong"), default=0),
        "run_id": str(report.get("run_id", "")),
        "generated_at": str(report.get("generated_at", "")),
        "backend_used": report.get("backend_used", []),
    }

    if n_sampled < min_samples:
        reason = (
            "LLM judge gate failed: insufficient sample size "
            f"({n_sampled} < {min_samples})."
        )
        details["reason"] = reason
        return False, reason, details

    if selected_precision < min_precision:
        reason = (
            "LLM judge gate failed: precision "
            f"{selected_precision:.4f} is below minimum {min_precision:.4f} "
            f"(mode={precision_mode})."
        )
        details["reason"] = reason
        return False, reason, details

    return True, "", details


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persist strategy with versioning + regression circuit breaker."
    )
    parser.add_argument("--concept-id", required=True, help="Concept ID")
    parser.add_argument(
        "--workspace", required=True, help="Workspace directory"
    )
    parser.add_argument(
        "--strategy", required=True, help="Path to updated strategy JSON file"
    )
    parser.add_argument("--note", default="", help="Update note")
    parser.add_argument(
        "--db", default=None, help="Corpus DB path (for regression testing)"
    )
    parser.add_argument(
        "--regression-threshold",
        type=float,
        default=0.10,
        help="Max allowed hit rate drop per group (default: 0.10)",
    )
    parser.add_argument(
        "--skip-regression",
        action="store_true",
        help="Skip regression check (for bootstrapping)",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents in regression evaluation.",
    )
    parser.add_argument(
        "--release-mode",
        action="store_true",
        help=(
            "Enable release gate checks; requires a valid --judge-report meeting "
            "precision thresholds."
        ),
    )
    parser.add_argument(
        "--judge-report",
        default=None,
        help="Optional llm_judge JSON report path for precision gate evaluation.",
    )
    parser.add_argument(
        "--min-judge-precision",
        type=float,
        default=0.80,
        help="Minimum accepted judge precision in release mode (default: 0.80).",
    )
    parser.add_argument(
        "--min-judge-samples",
        type=int,
        default=20,
        help="Minimum judge sample size in release mode (default: 20).",
    )
    parser.add_argument(
        "--judge-precision-mode",
        choices=("strict", "weighted"),
        default="strict",
        help="Judge precision metric used for gating (default: strict).",
    )
    parser.add_argument(
        "--concept-whitelist",
        default=None,
        help=(
            "Optional comma-separated concept-id whitelist for save enforcement. "
            "Supports exact IDs and subtree wildcards (e.g., family_id.*). "
            "Defaults to AGENT_CONCEPT_WHITELIST when unset."
        ),
    )
    parser.add_argument(
        "--out-of-scope-log",
        default=None,
        help=(
            "Optional JSONL path for out-of-scope discovery logging "
            "(default: <workspace>/out_of_scope_discoveries.jsonl)."
        ),
    )
    args = parser.parse_args()

    strategy_path = Path(args.strategy)
    if not strategy_path.exists():
        log(f"Error: strategy file not found at {strategy_path}")
        sys.exit(1)

    workspace = Path(args.workspace)
    strategies_dir = workspace / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    out_of_scope_log_path = (
        Path(args.out_of_scope_log)
        if args.out_of_scope_log
        else workspace / "out_of_scope_discoveries.jsonl"
    )
    effective_whitelist_raw = (
        args.concept_whitelist
        if args.concept_whitelist is not None
        else str(os.environ.get("AGENT_CONCEPT_WHITELIST", "") or "")
    )
    whitelist_exact, whitelist_prefixes = _parse_concept_whitelist(
        effective_whitelist_raw
    )
    whitelist_enabled = bool(whitelist_exact or whitelist_prefixes)
    whitelist_total = len(whitelist_exact) + len(whitelist_prefixes)

    # Load updated strategy (raw + resolved views)
    updated_strategy = load_json(strategy_path)
    log(f"Loaded updated strategy from {strategy_path}")

    if whitelist_enabled and not _concept_allowed(
        args.concept_id,
        exact=whitelist_exact,
        prefixes=whitelist_prefixes,
    ):
        _append_out_of_scope_log(
            out_of_scope_log_path,
            actor="strategy_writer",
            concept_id=args.concept_id,
            source=args.concept_id,
            reason="target_concept_not_in_whitelist",
            strategy_path=strategy_path,
        )
        reason = (
            f"Concept whitelist gate failed: target concept {args.concept_id} "
            "is not in AGENT_CONCEPT_WHITELIST."
        )
        log(f"REJECTED: {reason}")
        dump_json({
            "status": "rejected",
            "concept_id": args.concept_id,
            "reason": reason,
            "concept_whitelist_count": whitelist_total,
            "concept_whitelist_exact_count": len(whitelist_exact),
            "concept_whitelist_prefix_count": len(whitelist_prefixes),
            "out_of_scope_log": str(out_of_scope_log_path),
        })
        sys.exit(1)

    updated_strategy_resolved: dict[str, Any] | object = updated_strategy
    if isinstance(updated_strategy, dict):
        updated_strategy["template_overrides"] = normalize_template_overrides(
            updated_strategy.get("template_overrides", {})
        )
        try:
            updated_strategy_resolved = resolve_strategy_dict(
                updated_strategy,
                source_path=strategy_path,
                search_paths=(strategies_dir,),
            )
        except Exception as exc:
            reason = f"Failed to resolve strategy inheritance: {exc}"
            log(f"REJECTED: {reason}")
            dump_json({
                "status": "rejected",
                "concept_id": args.concept_id,
                "reason": reason,
            })
            sys.exit(1)
        if isinstance(updated_strategy_resolved, dict):
            updated_strategy_resolved["template_overrides"] = normalize_template_overrides(
                updated_strategy_resolved.get("template_overrides", {})
            )
        # Enforce concept whitelist before any costly checks.
        if whitelist_enabled:
            discovered_ids = set([args.concept_id])
            discovered_ids.update(_extract_strategy_concept_ids(updated_strategy))
            discovered_ids.update(_extract_strategy_concept_ids(updated_strategy_resolved))

            disallowed = sorted(
                cid for cid in discovered_ids
                if cid and not _concept_allowed(
                    cid,
                    exact=whitelist_exact,
                    prefixes=whitelist_prefixes,
                )
            )
            if disallowed:
                for cid in disallowed:
                    _append_out_of_scope_log(
                        out_of_scope_log_path,
                        actor="strategy_writer",
                        concept_id=cid,
                        source=args.concept_id,
                        reason="concept_not_in_whitelist",
                        strategy_path=strategy_path,
                    )
                reason = (
                    "Concept whitelist gate failed: discovered out-of-scope concept ids: "
                    + ", ".join(disallowed)
                )
                log(f"REJECTED: {reason}")
                dump_json({
                    "status": "rejected",
                    "concept_id": args.concept_id,
                    "reason": reason,
                    "concept_whitelist_count": whitelist_total,
                    "concept_whitelist_exact_count": len(whitelist_exact),
                    "concept_whitelist_prefix_count": len(whitelist_prefixes),
                    "disallowed_concepts": disallowed,
                    "out_of_scope_log": str(out_of_scope_log_path),
                })
                sys.exit(1)
        gate_target = (
            updated_strategy_resolved
            if isinstance(updated_strategy_resolved, dict)
            else updated_strategy
        )
        ok, gate_reason = ensure_strategy_v2_gates(gate_target)
        if not ok:
            log(f"REJECTED: {gate_reason}")
            dump_json({
                "status": "rejected",
                "concept_id": args.concept_id,
                "reason": gate_reason,
            })
            sys.exit(1)

    # Find current version
    current_version, current_path = find_latest_version(strategies_dir, args.concept_id)
    log(
        f"Current version: {current_version}"
        + (f" ({current_path})" if current_path else " (none)")
    )

    db_path = Path(args.db) if args.db else None
    v2_enabled = (
        isinstance(updated_strategy_resolved, dict)
        and updated_strategy_resolved.get("acceptance_policy_version", "v1") == "v2"
    )
    old_results: dict[str, dict] = {}
    new_results: dict[str, dict] = {}
    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    policy_checks: dict[str, Any] = {}
    judge_report_payload: dict[str, Any] | None = None

    if v2_enabled and (args.skip_regression or db_path is None):
        reason = (
            "Strategy v2 requires regression/policy evaluation. "
            "Provide --db and do not use --skip-regression."
        )
        log(f"REJECTED: {reason}")
        dump_json({
            "status": "rejected",
            "concept_id": args.concept_id,
            "reason": reason,
        })
        sys.exit(1)

    # Regression evaluation (and inputs for template stability policy).
    if not args.skip_regression and db_path:
        if not db_path.exists():
            reason = f"Database not found at {db_path}."
            if v2_enabled:
                log(f"REJECTED: {reason}")
                dump_json({
                    "status": "rejected",
                    "concept_id": args.concept_id,
                    "reason": reason,
                })
                sys.exit(1)
            log(f"Warning: {reason} Skipping regression check.")
        else:
            try:
                import duckdb
            except ImportError:
                reason = "duckdb not available."
                if v2_enabled:
                    log(f"REJECTED: {reason}")
                    dump_json({
                        "status": "rejected",
                        "concept_id": args.concept_id,
                        "reason": reason,
                    })
                    sys.exit(1)
                log(f"Warning: {reason} Skipping regression check.")
                duckdb = None

            if duckdb:
                log("Running regression check...")
                con = duckdb.connect(str(db_path), read_only=True)
                try:
                    ensure_schema_version(con, db_path=db_path)
                except SchemaVersionError as exc:
                    con.close()
                    log(f"Error: {exc}")
                    sys.exit(1)

                if current_path:
                    current_strategy = load_json(current_path)
                    current_strategy_resolved: dict[str, Any] | object = current_strategy
                    if isinstance(current_strategy, dict):
                        current_strategy["template_overrides"] = normalize_template_overrides(
                            current_strategy.get("template_overrides", {})
                        )
                        try:
                            current_strategy_resolved = resolve_strategy_dict(
                                current_strategy,
                                source_path=current_path,
                                search_paths=(strategies_dir,),
                            )
                        except Exception as exc:
                            reason = (
                                "Failed to resolve current strategy inheritance "
                                f"for regression check: {exc}"
                            )
                            log(f"REJECTED: {reason}")
                            dump_json({
                                "status": "rejected",
                                "concept_id": args.concept_id,
                                "reason": reason,
                            })
                            sys.exit(1)
                        if isinstance(current_strategy_resolved, dict):
                            current_strategy_resolved["template_overrides"] = normalize_template_overrides(
                                current_strategy_resolved.get("template_overrides", {})
                            )
                    old_results = run_strategy_against_docs(
                        current_strategy_resolved,
                        con,
                        args.concept_id,
                        cohort_only=not args.include_all,
                    )
                new_results = run_strategy_against_docs(
                    updated_strategy_resolved,
                    con,
                    args.concept_id,
                    cohort_only=not args.include_all,
                )
                con.close()

                if current_path:
                    ok, reason = validate_regression_results(old_results, new_results)
                    if not ok:
                        log(f"REJECTED: {reason}")
                        dump_json({
                            "status": "rejected",
                            "concept_id": args.concept_id,
                            "reason": reason,
                            "old_results": old_results,
                            "new_results": new_results,
                        })
                        sys.exit(1)

                    all_groups = set(old_results.keys()) | set(new_results.keys())
                    for group in sorted(all_groups):
                        old_rate = old_results.get(group, {}).get("hit_rate", 0.0)
                        new_rate = new_results.get(group, {}).get("hit_rate", 0.0)
                        delta = round(new_rate - old_rate, 4)

                        if delta < -args.regression_threshold:
                            regressions.append({
                                "group": group,
                                "old_rate": old_rate,
                                "new_rate": new_rate,
                                "delta": delta,
                            })
                        elif delta > 0:
                            improvements.append({
                                "group": group,
                                "old_rate": old_rate,
                                "new_rate": new_rate,
                                "delta": delta,
                            })

                    if regressions:
                        log(f"REGRESSION DETECTED: {len(regressions)} group(s) exceeded threshold")
                        dump_json({
                            "status": "rejected",
                            "concept_id": args.concept_id,
                            "reason": "Regression detected",
                            "regressions": regressions,
                            "improvements": improvements,
                        })
                        sys.exit(1)

                    log("Regression check passed")
                    if improvements:
                        log(f"Improvements in {len(improvements)} group(s)")

    # Strategy-v2 policy checks
    if v2_enabled:
        if not new_results:
            reason = "Strategy v2 policy checks require regression results, but none were produced."
            log(f"REJECTED: {reason}")
            dump_json({
                "status": "rejected",
                "concept_id": args.concept_id,
                "reason": reason,
            })
            sys.exit(1)

        resolved_dict = (
            updated_strategy_resolved
            if isinstance(updated_strategy_resolved, dict)
            else {}
        )
        outlier_policy = resolved_dict.get("outlier_policy", {})
        did_not_find_policy = resolved_dict.get("did_not_find_policy", {})
        confidence_policy = resolved_dict.get("confidence_policy", {})
        template_policy = resolved_dict.get("template_stability_policy", {})

        ok, reason, template_details = evaluate_template_stability_policy(
            new_results,
            template_policy,
        )
        policy_checks["template_stability"] = template_details
        if not ok:
            log(f"REJECTED: {reason}")
            dump_json({
                "status": "rejected",
                "concept_id": args.concept_id,
                "reason": reason,
                "template_stability": template_details,
                "new_results": new_results,
            })
            sys.exit(1)

        assert db_path is not None  # enforced above for v2
        ok, reason, outlier_details = run_outlier_policy_probe(
            strategy_path,
            db_path,
            outlier_policy,
            did_not_find_policy,
            confidence_policy,
            include_all=args.include_all,
        )
        policy_checks["outlier_policy"] = outlier_details
        if not ok:
            log(f"REJECTED: {reason}")
            dump_json({
                "status": "rejected",
                "concept_id": args.concept_id,
                "reason": reason,
                "outlier_policy": outlier_details,
            })
            sys.exit(1)

    # Optional or release-mode required LLM judge gate.
    if args.release_mode and not args.judge_report:
        reason = "Release mode requires --judge-report (llm_judge JSON output)."
        log(f"REJECTED: {reason}")
        dump_json({
            "status": "rejected",
            "concept_id": args.concept_id,
            "reason": reason,
        })
        sys.exit(1)

    if args.judge_report:
        judge_path = Path(args.judge_report)
        if not judge_path.exists():
            reason = f"Judge report not found at {judge_path}."
            log(f"REJECTED: {reason}")
            dump_json({
                "status": "rejected",
                "concept_id": args.concept_id,
                "reason": reason,
            })
            sys.exit(1)
        judge_loaded = load_json(judge_path)
        if not isinstance(judge_loaded, dict):
            reason = "Judge report payload must be a JSON object."
            log(f"REJECTED: {reason}")
            dump_json({
                "status": "rejected",
                "concept_id": args.concept_id,
                "reason": reason,
            })
            sys.exit(1)
        judge_report_payload = judge_loaded
        ok, reason, judge_details = evaluate_llm_judge_report(
            judge_report_payload,
            concept_id=args.concept_id,
            min_precision=max(0.0, min(1.0, float(args.min_judge_precision))),
            min_samples=max(1, int(args.min_judge_samples)),
            precision_mode=args.judge_precision_mode,
        )
        judge_details["report_path"] = str(judge_path)
        judge_details["release_mode"] = bool(args.release_mode)
        policy_checks["llm_judge"] = judge_details
        if not ok:
            log(f"REJECTED: {reason}")
            dump_json({
                "status": "rejected",
                "concept_id": args.concept_id,
                "reason": reason,
                "llm_judge": judge_details,
            })
            sys.exit(1)

    # Save new version
    new_version = current_version + 1
    version_str = f"v{new_version:03d}"
    new_filename = f"{args.concept_id}_{version_str}.json"
    new_path = strategies_dir / new_filename
    raw_view_path, resolved_view_path = _view_paths(
        strategies_dir,
        args.concept_id,
        version_str,
    )

    # Add metadata to strategy
    raw_payload_to_save: object = updated_strategy
    resolved_payload_to_save: object = updated_strategy_resolved
    if isinstance(updated_strategy, dict):
        meta = {
            "concept_id": args.concept_id,
            "version": new_version,
            "note": args.note,
            "previous_version": current_version if current_version > 0 else None,
        }
        updated_strategy["_meta"] = meta
        raw_payload_to_save = updated_strategy
        if isinstance(updated_strategy_resolved, dict):
            resolved_payload_to_save = dict(updated_strategy_resolved)
            resolved_payload_to_save["_meta"] = {
                **meta,
                "view": "resolved",
            }

    write_json(new_path, raw_payload_to_save)
    write_json(raw_view_path, raw_payload_to_save)
    write_json(resolved_view_path, resolved_payload_to_save)
    log(f"Wrote strategy to {new_path}")
    log(f"Wrote raw view: {raw_view_path}")
    log(f"Wrote resolved view: {resolved_view_path}")

    # Update current.json symlink (use a regular file copy for portability)
    current_link = strategies_dir / "current.json"
    try:
        if current_link.is_symlink() or current_link.exists():
            current_link.unlink()
        current_link.symlink_to(new_filename)
        log(f"Updated current.json -> {new_filename}")
    except OSError:
        # Fallback: write a redirect file
        write_json(current_link, {"current": new_filename, "version": new_version})
        log(f"Wrote current.json pointer to {new_filename}")

    judge_view_path: Path | None = None
    if judge_report_payload is not None:
        judge_view_path = strategies_dir / f"{args.concept_id}_{version_str}.judge.json"
        write_json(judge_view_path, judge_report_payload)
        log(f"Wrote judge view: {judge_view_path}")

    checkpoint_update: dict[str, Any] | None = None
    with contextlib.suppress(Exception):
        checkpoint_update = _update_workspace_checkpoint_after_save(
            workspace,
            concept_id=args.concept_id,
            strategy_path=new_path,
            version=new_version,
        )

    result_payload: dict[str, Any] = {
        "status": "saved",
        "concept_id": args.concept_id,
        "version": new_version,
        "path": str(new_path),
        "raw_view_path": str(raw_view_path),
        "resolved_view_path": str(resolved_view_path),
        "note": args.note,
    }
    if checkpoint_update is not None:
        result_payload["checkpoint_update"] = checkpoint_update
    if whitelist_enabled:
        result_payload["concept_whitelist"] = {
            "enabled": True,
            "count": whitelist_total,
            "exact_count": len(whitelist_exact),
            "prefix_count": len(whitelist_prefixes),
            "prefixes": list(whitelist_prefixes),
            "out_of_scope_log": str(out_of_scope_log_path),
        }
    if improvements:
        result_payload["improvements"] = improvements
    if policy_checks:
        result_payload["policy_checks"] = policy_checks
    if judge_view_path is not None:
        result_payload["judge_view_path"] = str(judge_view_path)
    dump_json(result_payload)


if __name__ == "__main__":
    main()
