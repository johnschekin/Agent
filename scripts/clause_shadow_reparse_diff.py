#!/usr/bin/env python3
"""Shadow reparse diff for clause parsing without rebuilding corpus index.

This script reparses selected sections from ``section_text`` in-memory using the
current parser code, compares the shadow output to persisted ``clauses`` rows,
and reports parser-quality deltas.

Primary use:
- Verify parser fixes before a full corpus rebuild.
- Quantify x/y parent-loss improvements and detect regressions.

Examples:
  python3 scripts/clause_shadow_reparse_diff.py \
    --db corpus_index/corpus.duckdb \
    --mode parent-loss \
    --json

  python3 scripts/clause_shadow_reparse_diff.py \
    --db corpus_index/corpus.duckdb \
    --mode all \
    --limit-sections 200 \
    --fail-on-regression \
    --max-structural-delta-ratio 0.25 \
    --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from agent.clause_parser import parse_clauses

try:
    import orjson

    def _dump_json(obj: object) -> bytes:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
except ImportError:

    def _dump_json(obj: object) -> bytes:
        return json.dumps(obj, indent=2, sort_keys=True, default=str).encode("utf-8")


_XY_MENTION_RE = re.compile(r"\([xy]\)", re.IGNORECASE)
_CONTINUATION_RE = re.compile(
    r"^\(\s*[xy]\s*\)\s*(and|or|that|any|on|the|to|if|for|in|with|no|all|each|such|as|pursuant)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _ClauseRow:
    doc_id: str
    section_number: str
    clause_id: str
    label: str
    depth: int
    level_type: str
    parent_id: str
    clause_text: str
    is_structural: bool
    span_start: int
    span_end: int
    parse_confidence: float


@dataclass(frozen=True, slots=True)
class _SectionTextRow:
    doc_id: str
    section_number: str
    text: str
    char_start: int


def _section_key(doc_id: str, section_number: str) -> tuple[str, str]:
    return (str(doc_id), str(section_number))


def _root_from_clause_id(clause_id: str) -> str:
    parts = str(clause_id or "").split(".", 1)
    return parts[0].strip().lower()


def _snippet(text: str, *, max_len: int = 200) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3] + "..."


def _ensure_required_tables(conn: duckdb.DuckDBPyConnection) -> None:
    existing = {
        str(row[0]).strip().lower()
        for row in conn.execute("SHOW TABLES").fetchall()
    }
    required = {"clauses", "section_text"}
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(f"Missing required table(s): {', '.join(missing)}")


def _build_doc_filter_sql(doc_ids: list[str]) -> tuple[str, list[Any]]:
    clean_ids = [str(doc_id).strip() for doc_id in doc_ids if str(doc_id).strip()]
    if not clean_ids:
        return "", []
    placeholders = ", ".join("?" for _ in clean_ids)
    return f" WHERE doc_id IN ({placeholders})", clean_ids


def _select_target_sections(
    conn: duckdb.DuckDBPyConnection,
    *,
    mode: str,
    doc_ids: list[str],
    limit_sections: int | None,
) -> list[tuple[str, str]]:
    doc_where, params = _build_doc_filter_sql(doc_ids)

    if mode == "parent-loss":
        base_sql = """
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
            sec AS (
              SELECT
                doc_id,
                section_number,
                bool_or(root = 'a') AS has_a_root,
                bool_or(root IN ('x', 'y')) AS has_xy_root,
                bool_or(
                  root = 'a'
                  AND regexp_matches(clause_text, '\\([xy]\\)')
                ) AS a_mentions_xy
              FROM depth1
              GROUP BY 1, 2
            )
            SELECT doc_id, section_number
            FROM sec
            WHERE has_a_root
              AND has_xy_root
              AND a_mentions_xy
        """
    elif mode == "all":
        base_sql = "SELECT doc_id, section_number FROM section_text"
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    sql = f"SELECT * FROM ({base_sql}) q{doc_where} ORDER BY doc_id, section_number"
    rows = conn.execute(sql, params).fetchall()
    sections = [(str(r[0]), str(r[1])) for r in rows]
    if limit_sections is not None and limit_sections >= 0:
        sections = sections[:limit_sections]
    return sections


def _load_section_text_rows(
    conn: duckdb.DuckDBPyConnection,
    sections: list[tuple[str, str]],
) -> list[_SectionTextRow]:
    if not sections:
        return []

    conn.execute("DROP TABLE IF EXISTS _shadow_selected_sections")
    conn.execute(
        """
        CREATE TEMP TABLE _shadow_selected_sections (
            doc_id VARCHAR,
            section_number VARCHAR
        )
        """,
    )
    conn.executemany(
        "INSERT INTO _shadow_selected_sections VALUES (?, ?)",
        sections,
    )

    rows = conn.execute(
        """
        SELECT
            st.doc_id,
            st.section_number,
            coalesce(st.text, '') AS text,
            coalesce(s.char_start, 0) AS char_start
        FROM section_text st
        JOIN _shadow_selected_sections ss
          ON ss.doc_id = st.doc_id
         AND ss.section_number = st.section_number
        LEFT JOIN sections s
          ON s.doc_id = st.doc_id
         AND s.section_number = st.section_number
        ORDER BY st.doc_id, st.section_number
        """,
    ).fetchall()

    return [
        _SectionTextRow(
            doc_id=str(row[0]),
            section_number=str(row[1]),
            text=str(row[2] or ""),
            char_start=int(row[3] or 0),
        )
        for row in rows
    ]


def _load_persisted_rows(
    conn: duckdb.DuckDBPyConnection,
    sections: list[tuple[str, str]],
) -> list[_ClauseRow]:
    if not sections:
        return []

    rows = conn.execute(
        """
        SELECT
            c.doc_id,
            c.section_number,
            c.clause_id,
            coalesce(c.label, ''),
            coalesce(c.depth, 0),
            coalesce(c.level_type, ''),
            coalesce(c.parent_id, ''),
            coalesce(c.clause_text, ''),
            coalesce(c.is_structural, false),
            coalesce(c.span_start, 0),
            coalesce(c.span_end, 0),
            coalesce(c.parse_confidence, 0.0)
        FROM clauses c
        JOIN _shadow_selected_sections ss
          ON ss.doc_id = c.doc_id
         AND ss.section_number = c.section_number
        ORDER BY c.doc_id, c.section_number, c.span_start, c.clause_id
        """,
    ).fetchall()

    return [
        _ClauseRow(
            doc_id=str(row[0]),
            section_number=str(row[1]),
            clause_id=str(row[2]),
            label=str(row[3]),
            depth=int(row[4] or 0),
            level_type=str(row[5]),
            parent_id=str(row[6]),
            clause_text=str(row[7]),
            is_structural=bool(row[8]),
            span_start=int(row[9] or 0),
            span_end=int(row[10] or 0),
            parse_confidence=float(row[11] or 0.0),
        )
        for row in rows
    ]


def _shadow_reparse(section_rows: list[_SectionTextRow]) -> list[_ClauseRow]:
    shadow: list[_ClauseRow] = []
    for sec in section_rows:
        nodes = parse_clauses(sec.text, global_offset=sec.char_start)
        for node in nodes:
            local_start = max(0, node.span_start - sec.char_start)
            local_end = max(local_start, node.span_end - sec.char_start)
            local_end = min(local_end, len(sec.text))
            clause_text = sec.text[local_start:local_end] if local_start <= local_end else ""
            shadow.append(
                _ClauseRow(
                    doc_id=sec.doc_id,
                    section_number=sec.section_number,
                    clause_id=node.id,
                    label=node.label,
                    depth=int(node.depth),
                    level_type=node.level_type,
                    parent_id=node.parent_id,
                    clause_text=clause_text,
                    is_structural=bool(node.is_structural_candidate),
                    span_start=int(node.span_start),
                    span_end=int(node.span_end),
                    parse_confidence=float(node.parse_confidence),
                ),
            )
    return shadow


def _compute_parent_loss_metrics(rows: list[_ClauseRow]) -> dict[str, int | float]:
    section_state: dict[tuple[str, str], dict[str, Any]] = {}
    suspicious_rows: list[_ClauseRow] = []
    for row in rows:
        if not row.is_structural or str(row.parent_id or "").strip() != "":
            continue
        key = _section_key(row.doc_id, row.section_number)
        state = section_state.setdefault(
            key,
            {"roots": set(), "a_mentions_xy": False},
        )
        root = _root_from_clause_id(row.clause_id)
        state["roots"].add(root)
        if root == "a" and _XY_MENTION_RE.search(row.clause_text.lower()):
            state["a_mentions_xy"] = True

    suspicious_sections: dict[tuple[str, str], int] = {}
    for key, state in section_state.items():
        roots = set(state["roots"])
        has_a_root = "a" in roots
        has_xy_root = "x" in roots or "y" in roots
        if has_a_root and has_xy_root and bool(state["a_mentions_xy"]):
            suspicious_sections[key] = len(roots)

    for row in rows:
        key = _section_key(row.doc_id, row.section_number)
        if key not in suspicious_sections:
            continue
        if not row.is_structural or str(row.parent_id or "").strip() != "":
            continue
        root = _root_from_clause_id(row.clause_id)
        if root in {"x", "y"}:
            suspicious_rows.append(row)

    docs = {doc_id for (doc_id, _) in suspicious_sections}
    sections_low_root_count = sum(
        1 for root_count in suspicious_sections.values() if root_count <= 3
    )
    structural_rows = len(suspicious_rows)
    continuation_like_rows = sum(
        1 for row in suspicious_rows if _CONTINUATION_RE.search(row.clause_text.lower())
    )
    continuation_like_ratio = (
        float(continuation_like_rows) / float(structural_rows)
        if structural_rows > 0
        else 0.0
    )

    return {
        "docs": len(docs),
        "sections": len(suspicious_sections),
        "sections_low_root_count": sections_low_root_count,
        "structural_rows": structural_rows,
        "continuation_like_rows": continuation_like_rows,
        "continuation_like_ratio": continuation_like_ratio,
    }


def _compute_root_xy_section_map(rows: list[_ClauseRow]) -> dict[tuple[str, str], set[str]]:
    by_section: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        if not row.is_structural or str(row.parent_id or "").strip() != "":
            continue
        root = _root_from_clause_id(row.clause_id)
        if root not in {"x", "y", "z"}:
            continue
        by_section.setdefault(
            _section_key(row.doc_id, row.section_number),
            set(),
        ).add(row.clause_id)
    return by_section


def _compute_section_counts(rows: list[_ClauseRow]) -> dict[tuple[str, str], dict[str, int]]:
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        key = _section_key(row.doc_id, row.section_number)
        bucket = counts.setdefault(key, {"total": 0, "structural": 0})
        bucket["total"] += 1
        if row.is_structural:
            bucket["structural"] += 1
    return counts


def _rows_by_key(rows: list[_ClauseRow]) -> dict[tuple[str, str, str], _ClauseRow]:
    out: dict[tuple[str, str, str], _ClauseRow] = {}
    for row in rows:
        out[(row.doc_id, row.section_number, row.clause_id)] = row
    return out


def _summarize(
    *,
    persisted_rows: list[_ClauseRow],
    shadow_rows: list[_ClauseRow],
    samples: int,
) -> dict[str, Any]:
    persisted_parent_loss = _compute_parent_loss_metrics(persisted_rows)
    shadow_parent_loss = _compute_parent_loss_metrics(shadow_rows)

    persisted_xy = _compute_root_xy_section_map(persisted_rows)
    shadow_xy = _compute_root_xy_section_map(shadow_rows)
    all_sections = set(persisted_xy) | set(shadow_xy)
    fixed_sections = sorted(
        key for key in all_sections if bool(persisted_xy.get(key)) and not bool(shadow_xy.get(key))
    )
    regressed_sections = sorted(
        key for key in all_sections if not bool(persisted_xy.get(key)) and bool(shadow_xy.get(key))
    )
    unchanged_sections = sorted(
        key for key in all_sections if bool(persisted_xy.get(key)) and bool(shadow_xy.get(key))
    )

    persisted_structural = [row for row in persisted_rows if row.is_structural]
    shadow_structural = [row for row in shadow_rows if row.is_structural]
    persisted_keyed = _rows_by_key(persisted_structural)
    shadow_keyed = _rows_by_key(shadow_structural)
    persisted_keys = set(persisted_keyed)
    shadow_keys = set(shadow_keyed)
    removed_keys = sorted(persisted_keys - shadow_keys)
    added_keys = sorted(shadow_keys - persisted_keys)

    persisted_counts = _compute_section_counts(persisted_rows)
    shadow_counts = _compute_section_counts(shadow_rows)
    all_count_sections = sorted(set(persisted_counts) | set(shadow_counts))
    section_drifts: list[dict[str, Any]] = []
    for key in all_count_sections:
        p = persisted_counts.get(key, {"total": 0, "structural": 0})
        s = shadow_counts.get(key, {"total": 0, "structural": 0})
        total_delta = int(s["total"]) - int(p["total"])
        structural_delta = int(s["structural"]) - int(p["structural"])
        if total_delta == 0 and structural_delta == 0:
            continue
        section_drifts.append(
            {
                "doc_id": key[0],
                "section_number": key[1],
                "persisted_total": int(p["total"]),
                "shadow_total": int(s["total"]),
                "total_delta": total_delta,
                "persisted_structural": int(p["structural"]),
                "shadow_structural": int(s["structural"]),
                "structural_delta": structural_delta,
            },
        )
    section_drifts.sort(
        key=lambda row: (
            -abs(int(row["structural_delta"])),
            -abs(int(row["total_delta"])),
            str(row["doc_id"]),
            str(row["section_number"]),
        ),
    )

    def _sample_section_keys(keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
        return [
            {"doc_id": doc_id, "section_number": section_number}
            for doc_id, section_number in keys[:samples]
        ]

    removed_samples = [
        {
            "doc_id": doc_id,
            "section_number": section_number,
            "clause_id": clause_id,
            "label": persisted_keyed[(doc_id, section_number, clause_id)].label,
            "snippet": _snippet(persisted_keyed[(doc_id, section_number, clause_id)].clause_text),
        }
        for (doc_id, section_number, clause_id) in removed_keys[:samples]
    ]
    added_samples = [
        {
            "doc_id": doc_id,
            "section_number": section_number,
            "clause_id": clause_id,
            "label": shadow_keyed[(doc_id, section_number, clause_id)].label,
            "snippet": _snippet(shadow_keyed[(doc_id, section_number, clause_id)].clause_text),
        }
        for (doc_id, section_number, clause_id) in added_keys[:samples]
    ]

    persisted_structural_count = len(persisted_structural)
    shadow_structural_count = len(shadow_structural)
    structural_delta = shadow_structural_count - persisted_structural_count
    structural_delta_ratio = (
        abs(structural_delta) / float(persisted_structural_count)
        if persisted_structural_count > 0
        else float(abs(structural_delta))
    )

    return {
        "persisted_metrics": {
            "rows_total": len(persisted_rows),
            "rows_structural": persisted_structural_count,
            "xy_parent_loss": persisted_parent_loss,
            "sections_with_root_xy": len(persisted_xy),
        },
        "shadow_metrics": {
            "rows_total": len(shadow_rows),
            "rows_structural": shadow_structural_count,
            "xy_parent_loss": shadow_parent_loss,
            "sections_with_root_xy": len(shadow_xy),
        },
        "delta_metrics": {
            "rows_total_delta": len(shadow_rows) - len(persisted_rows),
            "rows_structural_delta": structural_delta,
            "rows_structural_delta_ratio_abs": structural_delta_ratio,
            "xy_parent_loss_sections_delta": int(shadow_parent_loss["sections"])
            - int(persisted_parent_loss["sections"]),
            "root_xy_sections_delta": len(shadow_xy) - len(persisted_xy),
        },
        "section_signals": {
            "fixed_root_xy_sections": len(fixed_sections),
            "regressed_root_xy_sections": len(regressed_sections),
            "unchanged_root_xy_sections": len(unchanged_sections),
            "fixed_root_xy_samples": _sample_section_keys(fixed_sections),
            "regressed_root_xy_samples": _sample_section_keys(regressed_sections),
            "unchanged_root_xy_samples": _sample_section_keys(unchanged_sections),
        },
        "structural_key_diff": {
            "removed_count": len(removed_keys),
            "added_count": len(added_keys),
            "removed_samples": removed_samples,
            "added_samples": added_samples,
        },
        "section_drift": {
            "changed_sections": len(section_drifts),
            "top_changed_samples": section_drifts[:samples],
        },
    }


def _evaluate_failures(
    summary: dict[str, Any],
    *,
    max_structural_delta_ratio: float | None,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    persisted_parent = summary["persisted_metrics"]["xy_parent_loss"]
    shadow_parent = summary["shadow_metrics"]["xy_parent_loss"]
    persisted_root_xy = int(summary["persisted_metrics"]["sections_with_root_xy"])
    shadow_root_xy = int(summary["shadow_metrics"]["sections_with_root_xy"])
    regressed_sections = int(summary["section_signals"]["regressed_root_xy_sections"])

    if int(shadow_parent["sections"]) > int(persisted_parent["sections"]):
        failures.append(
            {
                "metric": "xy_parent_loss.sections",
                "persisted": int(persisted_parent["sections"]),
                "shadow": int(shadow_parent["sections"]),
                "reason": "shadow_increase",
            },
        )
    if int(shadow_parent["sections_low_root_count"]) > int(
        persisted_parent["sections_low_root_count"]
    ):
        failures.append(
            {
                "metric": "xy_parent_loss.sections_low_root_count",
                "persisted": int(persisted_parent["sections_low_root_count"]),
                "shadow": int(shadow_parent["sections_low_root_count"]),
                "reason": "shadow_increase",
            },
        )
    if shadow_root_xy > persisted_root_xy:
        failures.append(
            {
                "metric": "sections_with_root_xy",
                "persisted": persisted_root_xy,
                "shadow": shadow_root_xy,
                "reason": "shadow_increase",
            },
        )
    if regressed_sections > 0:
        failures.append(
            {
                "metric": "regressed_root_xy_sections",
                "persisted": 0,
                "shadow": regressed_sections,
                "reason": "new_regression_sections",
            },
        )

    if max_structural_delta_ratio is not None:
        ratio = float(summary["delta_metrics"]["rows_structural_delta_ratio_abs"])
        if ratio > max_structural_delta_ratio:
            failures.append(
                {
                    "metric": "rows_structural_delta_ratio_abs",
                    "persisted": 0.0,
                    "shadow": ratio,
                    "limit": max_structural_delta_ratio,
                    "reason": "exceeds_limit",
                },
            )

    return failures


def _print_human(payload: dict[str, Any]) -> None:
    status = str(payload.get("status", "unknown")).upper()
    print(f"Status: {status}")
    print(f"Mode: {payload.get('mode')}")
    print(f"Sections selected: {payload.get('sections_selected')}")
    pm = payload["summary"]["persisted_metrics"]
    sm = payload["summary"]["shadow_metrics"]
    dm = payload["summary"]["delta_metrics"]
    print(
        "Parent-loss sections: "
        f"persisted={pm['xy_parent_loss']['sections']} "
        f"shadow={sm['xy_parent_loss']['sections']} "
        f"delta={dm['xy_parent_loss_sections_delta']}",
    )
    print(
        "Root x/y sections: "
        f"persisted={pm['sections_with_root_xy']} "
        f"shadow={sm['sections_with_root_xy']} "
        f"delta={dm['root_xy_sections_delta']}",
    )
    print(
        "Structural rows: "
        f"persisted={pm['rows_structural']} "
        f"shadow={sm['rows_structural']} "
        f"delta={dm['rows_structural_delta']}",
    )
    signals = payload["summary"]["section_signals"]
    print(
        "Section signals: "
        f"fixed={signals['fixed_root_xy_sections']} "
        f"regressed={signals['regressed_root_xy_sections']} "
        f"unchanged={signals['unchanged_root_xy_sections']}",
    )
    failures = payload.get("failures", [])
    if failures:
        print("Failures:")
        for failure in failures:
            print(
                f"  - {failure.get('metric')}: {failure.get('reason')} "
                f"(persisted={failure.get('persisted')}, shadow={failure.get('shadow')})",
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Path to DuckDB corpus index")
    parser.add_argument(
        "--mode",
        choices=("parent-loss", "all"),
        default="parent-loss",
        help="Section selection mode",
    )
    parser.add_argument(
        "--doc-id",
        action="append",
        default=[],
        help="Optional doc_id filter (repeatable)",
    )
    parser.add_argument(
        "--limit-sections",
        type=int,
        default=500,
        help="Max sections to reparse; set -1 for no limit",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=20,
        help="Max sample rows/sections to include in payload",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit non-zero if shadow metrics regress",
    )
    parser.add_argument(
        "--max-structural-delta-ratio",
        type=float,
        default=None,
        help="Optional absolute structural row delta ratio limit when using --fail-on-regression",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON payload to stdout")
    parser.add_argument("--output", type=Path, default=None, help="Write payload JSON to file")
    args = parser.parse_args(argv)

    if args.limit_sections is not None and args.limit_sections < 0:
        limit_sections: int | None = None
    else:
        limit_sections = int(args.limit_sections)

    try:
        conn = duckdb.connect(str(args.db), read_only=True)
    except Exception as exc:  # pragma: no cover - connection failure path
        print(f"Failed to open DB: {args.db} ({exc})", file=sys.stderr)
        return 2

    try:
        _ensure_required_tables(conn)
        sections = _select_target_sections(
            conn,
            mode=args.mode,
            doc_ids=list(args.doc_id),
            limit_sections=limit_sections,
        )
        section_rows = _load_section_text_rows(conn, sections)
        persisted_rows = _load_persisted_rows(conn, sections)
        shadow_rows = _shadow_reparse(section_rows)
    except Exception as exc:
        print(f"Failed to compute shadow reparse diff: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    summary = _summarize(
        persisted_rows=persisted_rows,
        shadow_rows=shadow_rows,
        samples=max(1, int(args.samples)),
    )
    failures: list[dict[str, Any]] = []
    if args.fail_on_regression:
        failures = _evaluate_failures(
            summary,
            max_structural_delta_ratio=args.max_structural_delta_ratio,
        )
    status = "pass" if not failures else "fail"

    payload: dict[str, Any] = {
        "status": status,
        "db": str(args.db),
        "mode": args.mode,
        "sections_selected": len(section_rows),
        "docs_selected": len({row.doc_id for row in section_rows}),
        "fail_on_regression": bool(args.fail_on_regression),
        "summary": summary,
        "failures": failures,
    }

    encoded = _dump_json(payload)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded)

    if args.json:
        sys.stdout.write(encoded.decode("utf-8") + "\n")
    else:
        _print_human(payload)
        if args.output is not None:
            print(f"Wrote JSON report: {args.output}")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
