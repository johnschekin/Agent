#!/usr/bin/env python3
"""Seed v1 gold fixtures from corpus edge-case hotspots.

This script builds an initial fixture pack suitable for:
1) deterministic parser regression testing, and
2) future ML/LLM training/evaluation.

Output defaults to:
  data/fixtures/gold/v1/fixtures.jsonl
  data/fixtures/gold/v1/splits.v1.manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "corpus_index" / "corpus.duckdb"
DEFAULT_FIXTURES = ROOT / "data" / "fixtures" / "gold" / "v1" / "fixtures.jsonl"
DEFAULT_SPLITS = ROOT / "data" / "fixtures" / "gold" / "v1" / "splits.v1.manifest.json"
DEFAULT_REASON_CODES = ROOT / "data" / "fixtures" / "gold" / "v1" / "reason_codes.v1.json"
DEFAULT_RUN_MANIFEST = ROOT / "corpus_index" / "run_manifest.json"

AMBIGUOUS_LABELS = ("i", "v", "x", "l", "c", "d", "m")
QUOTA_PROFILES: dict[str, dict[str, int]] = {
    "default": {},
    "hard_parser": {
        "ambiguous_alpha_roman": 22,
        "high_letter_continuation": 22,
        "nonstruct_parent_chain": 16,
        "xref_vs_structural": 14,
        "true_root_high_letter": 10,
        "deep_nesting_chain": 5,
        "defined_term_boundary": 4,
        "duplicate_collision": 3,
        "formatting_noise": 2,
        "linking_contract": 2,
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _snapshot_id(path: Path) -> str:
    if path.exists():
        payload = _load_json(path)
        run_id = str(payload.get("run_id") or "").strip()
        if run_id:
            return run_id
    return "snapshot_unknown"


def _split_for_doc(doc_id: str) -> str:
    digest = hashlib.sha1(doc_id.encode("utf-8")).hexdigest()  # noqa: S324
    bucket = int(digest[:8], 16) % 100
    if bucket < 60:
        return "train"
    if bucket < 75:
        return "val"
    if bucket < 90:
        return "test"
    return "holdout"


def _cohort_join(cohort_only: bool) -> str:
    if not cohort_only:
        return ""
    return " JOIN documents d ON d.doc_id = t.doc_id WHERE d.cohort_included = true "


def _fetch_candidates(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    cohort_only: bool,
    limit: int,
) -> list[tuple[str, str, float]]:
    wrapped = f"SELECT t.doc_id, t.section_number, t.score FROM ({sql}) t"
    if cohort_only:
        wrapped += _cohort_join(True)
    wrapped += " ORDER BY t.score DESC, t.doc_id, t.section_number LIMIT ?"
    rows = conn.execute(wrapped, [limit]).fetchall()
    return [(str(r[0]), str(r[1]), float(r[2] or 0.0)) for r in rows]


def _category_specs(quota_profile: str = "default") -> list[dict[str, Any]]:
    specs = [
        {
            "category": "ambiguous_alpha_roman",
            "quota": 14,
            "decision": "review",
            "ambiguity_class": "A1",
            "reason_codes": ["ABS_ALPHA_ROMAN_CONFLICT"],
            "sql": """
                WITH base AS (
                  SELECT
                    doc_id,
                    section_number,
                    lower(regexp_extract(label, '\\(([A-Za-z0-9]+)\\)', 1)) AS lbl,
                    level_type
                  FROM clauses
                  WHERE is_structural = true
                    AND regexp_extract(label, '\\(([A-Za-z0-9]+)\\)', 1) <> ''
                )
                SELECT
                  doc_id,
                  section_number,
                  COUNT(*) AS score
                FROM base
                WHERE lbl IN ('i','v','x','l','c','d','m')
                GROUP BY 1, 2
                HAVING COUNT(DISTINCT level_type) >= 2
            """,
        },
        {
            "category": "high_letter_continuation",
            "quota": 14,
            "decision": "review",
            "ambiguity_class": "A1",
            "reason_codes": ["REV_INLINE_CONTINUATION_SUSPECTED"],
            "sql": """
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
                  SELECT doc_id, section_number, COUNT(DISTINCT root) AS root_count
                  FROM depth1
                  GROUP BY 1, 2
                ),
                sec AS (
                  SELECT
                    d.doc_id,
                    d.section_number,
                    COALESCE(r.root_count, 0) AS root_count,
                    bool_or(d.root = 'a') AS has_a_root,
                    bool_or(d.root IN ('x', 'y', 'z')) AS has_xyz_root,
                    bool_or(d.root = 'a' AND regexp_matches(d.clause_text, '\\([xy]\\)')) AS a_mentions_xy
                  FROM depth1 d
                  LEFT JOIN root_counts r USING (doc_id, section_number)
                  GROUP BY 1, 2, 3
                )
                SELECT doc_id, section_number, (100 - least(root_count, 100)) AS score
                FROM sec
                WHERE has_a_root AND has_xyz_root AND a_mentions_xy
            """,
        },
        {
            "category": "xref_vs_structural",
            "quota": 10,
            "decision": "abstain",
            "ambiguity_class": "A2",
            "reason_codes": ["ABS_XREF_STRUCTURAL_CONFLICT"],
            "sql": """
                SELECT
                  doc_id,
                  section_number,
                  COUNT(*) AS score
                FROM clauses
                WHERE is_structural = true
                  AND depth = 1
                  AND regexp_matches(
                    lower(coalesce(clause_text, '')),
                    '^\\(\\s*[a-zivxlcdm0-9]+\\s*\\)\\s*(subject to|pursuant to|in accordance with|defined in|under)\\b'
                  )
                GROUP BY 1, 2
            """,
        },
        {
            "category": "deep_nesting_chain",
            "quota": 10,
            "decision": "accepted",
            "ambiguity_class": "none",
            "reason_codes": ["INFO_CONTROL_POSITIVE"],
            "sql": """
                SELECT
                  doc_id,
                  section_number,
                  MAX(ARRAY_LENGTH(STRING_SPLIT(clause_id, '.'))) * 100
                    + COUNT(*) FILTER (WHERE is_structural = true) AS score
                FROM clauses
                GROUP BY 1, 2
                HAVING MAX(ARRAY_LENGTH(STRING_SPLIT(clause_id, '.'))) >= 4
            """,
        },
        {
            "category": "nonstruct_parent_chain",
            "quota": 10,
            "decision": "review",
            "ambiguity_class": "A1",
            "reason_codes": ["REV_NONSTRUCT_PARENT_CHAIN"],
            "sql": """
                SELECT
                  c.doc_id,
                  c.section_number,
                  COUNT(*) AS score
                FROM clauses c
                JOIN clauses p
                  ON p.doc_id = c.doc_id
                 AND p.section_number = c.section_number
                 AND p.clause_id = c.parent_id
                WHERE c.is_structural = true
                  AND c.parent_id != ''
                  AND COALESCE(p.is_structural, false) = false
                GROUP BY 1, 2
            """,
        },
        {
            "category": "duplicate_collision",
            "quota": 10,
            "decision": "review",
            "ambiguity_class": "A1",
            "reason_codes": ["INFO_CONTROL_NEGATIVE"],
            "sql": """
                SELECT
                  doc_id,
                  section_number,
                  COUNT(*) AS score
                FROM clauses
                WHERE clause_id LIKE '%\\_dup%' ESCAPE '\\'
                GROUP BY 1, 2
            """,
        },
        {
            "category": "defined_term_boundary",
            "quota": 10,
            "decision": "review",
            "ambiguity_class": "A2",
            "reason_codes": ["REV_DEFINED_TERM_BOUNDARY"],
            "sql": """
                WITH mapped AS (
                  SELECT
                    d.doc_id,
                    s.section_number,
                    d.term,
                    LENGTH(coalesce(d.definition_text, '')) AS def_len
                  FROM definitions d
                  JOIN sections s
                    ON s.doc_id = d.doc_id
                   AND d.char_start BETWEEN s.char_start AND s.char_end
                  WHERE d.term IS NOT NULL
                )
                SELECT
                  doc_id,
                  section_number,
                  SUM(CASE WHEN lower(term) LIKE '%ebitda%' THEN 5 ELSE 1 END) + MAX(def_len) / 200.0 AS score
                FROM mapped
                GROUP BY 1, 2
                HAVING MAX(def_len) >= 600
            """,
        },
        {
            "category": "formatting_noise",
            "quota": 8,
            "decision": "abstain",
            "ambiguity_class": "A3",
            "reason_codes": ["SRC_LAYOUT_FLATTENED"],
            "sql": """
                SELECT
                  s.doc_id,
                  s.section_number,
                  CASE
                    WHEN regexp_matches(s.section_number, '[A-Za-z]') THEN 50
                    ELSE 0
                  END
                  + CASE
                    WHEN trim(coalesce(s.heading, '')) = '' THEN 30
                    ELSE 0
                  END
                  + least(coalesce(s.word_count, 0) / 100, 40) AS score
                FROM sections s
                WHERE regexp_matches(s.section_number, '[A-Za-z]')
                   OR trim(coalesce(s.heading, '')) = ''
                   OR coalesce(s.word_count, 0) >= 1800
            """,
        },
        {
            "category": "true_root_high_letter",
            "quota": 8,
            "decision": "review",
            "ambiguity_class": "A1",
            "reason_codes": ["REV_TRUE_ROOT_HIGH_LETTER"],
            "sql": """
                WITH roots AS (
                  SELECT
                    doc_id,
                    section_number,
                    lower(split_part(clause_id, '.', 1)) AS root
                  FROM clauses
                  WHERE is_structural = true
                    AND depth = 1
                ),
                agg AS (
                  SELECT
                    doc_id,
                    section_number,
                    COUNT(DISTINCT root) AS root_count,
                    bool_or(root = 'a') AS has_a,
                    bool_or(root IN ('x', 'y', 'z')) AS has_xyz
                  FROM roots
                  GROUP BY 1, 2
                )
                SELECT
                  doc_id,
                  section_number,
                  root_count AS score
                FROM agg
                WHERE has_a
                  AND has_xyz
                  AND root_count >= 18
            """,
        },
        {
            "category": "linking_contract",
            "quota": 6,
            "decision": "accepted",
            "ambiguity_class": "none",
            "reason_codes": ["INFO_CONTROL_POSITIVE"],
            "sql": """
                SELECT
                  s.doc_id,
                  s.section_number,
                  1
                  + CASE WHEN lower(coalesce(s.heading, '')) LIKE '%incremental%' THEN 5 ELSE 0 END
                  + CASE WHEN lower(coalesce(s.heading, '')) LIKE '%indebtedness%' THEN 5 ELSE 0 END
                  + CASE WHEN lower(coalesce(s.heading, '')) LIKE '%liens%' THEN 4 ELSE 0 END
                  + CASE WHEN lower(coalesce(s.heading, '')) LIKE '%restricted payments%' THEN 4 ELSE 0 END
                  + CASE WHEN lower(coalesce(s.heading, '')) LIKE '%events of default%' THEN 4 ELSE 0 END
                  + CASE WHEN lower(coalesce(s.heading, '')) LIKE '%investments%' THEN 4 ELSE 0 END AS score
                FROM sections s
                WHERE lower(coalesce(s.heading, '')) LIKE '%incremental%'
                   OR lower(coalesce(s.heading, '')) LIKE '%indebtedness%'
                   OR lower(coalesce(s.heading, '')) LIKE '%liens%'
                   OR lower(coalesce(s.heading, '')) LIKE '%restricted payments%'
                   OR lower(coalesce(s.heading, '')) LIKE '%events of default%'
                   OR lower(coalesce(s.heading, '')) LIKE '%investments%'
            """,
        },
    ]

    profile = QUOTA_PROFILES.get(quota_profile, {})
    if profile:
        for spec in specs:
            category = str(spec.get("category") or "")
            if category in profile:
                spec["quota"] = int(profile[category])
    return specs


def _load_section(
    conn: duckdb.DuckDBPyConnection,
    doc_id: str,
    section_number: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
          s.doc_id,
          s.section_number,
          coalesce(s.heading, '') AS heading,
          coalesce(s.char_start, 0) AS char_start,
          coalesce(s.char_end, 0) AS char_end,
          coalesce(s.article_num, 0) AS article_num,
          coalesce(s.word_count, 0) AS word_count,
          coalesce(st.text, '') AS text
        FROM sections s
        LEFT JOIN section_text st
          ON st.doc_id = s.doc_id
         AND st.section_number = s.section_number
        WHERE s.doc_id = ? AND s.section_number = ?
        LIMIT 1
        """,
        [doc_id, section_number],
    ).fetchone()
    if row is None:
        return None
    return {
        "doc_id": str(row[0]),
        "section_number": str(row[1]),
        "heading": str(row[2] or ""),
        "char_start": int(row[3] or 0),
        "char_end": int(row[4] or 0),
        "article_num": int(row[5] or 0),
        "word_count": int(row[6] or 0),
        "text": str(row[7] or ""),
    }


def _load_clauses(
    conn: duckdb.DuckDBPyConnection,
    doc_id: str,
    section_number: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          clause_id,
          label,
          parent_id,
          depth,
          level_type,
          span_start,
          span_end,
          is_structural,
          parse_confidence
        FROM clauses
        WHERE doc_id = ? AND section_number = ?
        ORDER BY span_start, clause_id
        """,
        [doc_id, section_number],
    ).fetchall()
    return [
        {
            "clause_id": str(r[0] or ""),
            "label": str(r[1] or ""),
            "parent_id": str(r[2] or ""),
            "depth": int(r[3] or 0),
            "level_type": str(r[4] or ""),
            "span_start": int(r[5] or 0),
            "span_end": int(r[6] or 0),
            "is_structural": bool(r[7]),
            "parse_confidence": float(r[8] or 0.0),
        }
        for r in rows
    ]


def _xref_flags_from_parser(section_text: str, char_start: int) -> dict[str, bool]:
    # Local import keeps this script usable without parser path issues when not executed.
    from agent.clause_parser import parse_clauses  # noqa: PLC0415

    node_map: dict[str, bool] = {}
    for n in parse_clauses(section_text, global_offset=char_start):
        node_map[str(n.id)] = bool(n.xref_suspected)
    return node_map


def _fixture_for_section(
    conn: duckdb.DuckDBPyConnection,
    *,
    fixture_id: str,
    spec: dict[str, Any],
    doc_id: str,
    section_number: str,
    score: float,
    snapshot_id: str,
) -> dict[str, Any] | None:
    section = _load_section(conn, doc_id, section_number)
    if section is None:
        return None
    if not section["text"].strip():
        return None

    clauses = _load_clauses(conn, doc_id, section_number)
    if not clauses:
        return None

    xref_map = _xref_flags_from_parser(section["text"], section["char_start"])
    split = _split_for_doc(doc_id)

    gold_nodes: list[dict[str, Any]] = []
    for c in clauses:
        span_start = int(c["span_start"])
        span_end = int(c["span_end"])
        if span_end < span_start:
            span_end = span_start
        gold_nodes.append(
            {
                "clause_id": c["clause_id"],
                "label": c["label"],
                "parent_id": c["parent_id"],
                "depth": c["depth"],
                "level_type": c["level_type"],
                "span_start": span_start,
                "span_end": span_end,
                "is_structural": c["is_structural"],
                "xref_suspected": bool(xref_map.get(c["clause_id"], False)),
                "confidence_band": (
                    "high"
                    if c["parse_confidence"] >= 0.8
                    else "medium"
                    if c["parse_confidence"] >= 0.5
                    else "low"
                ),
            },
        )

    return {
        "fixture_id": fixture_id,
        "schema_version": "gold-fixture-v1",
        "category": spec["category"],
        "source_type": "corpus",
        "source": {
            "doc_id": doc_id,
            "section_number": section_number,
            "snapshot_id": snapshot_id,
            "candidate_score": round(score, 4),
        },
        "text": {
            "raw_text": section["text"],
            "char_start": section["char_start"],
            "char_end": section["char_end"],
            "normalization": {
                "engine": "document_processor.normalize_text",
                "version": "v1",
            },
        },
        "section_meta": {
            "heading": section["heading"],
            "article_num": section["article_num"],
            "word_count": section["word_count"],
        },
        "gold_nodes": gold_nodes,
        "gold_decision": spec["decision"],
        "reason_codes": list(spec["reason_codes"]),
        "adjudication": {
            "human_verified": False,
            "ambiguity_class": spec["ambiguity_class"],
            "adjudicator_id": "auto_seed_v1",
            "adjudicated_at": None,
            "rationale": f"Auto-seeded from {spec['category']} hotspot query.",
        },
        "split": split,
        "tags": ["seeded", "corpus", "parser"],
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output exists: {path}. Pass --overwrite to replace.")
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def _write_split_manifest(path: Path, fixtures: list[dict[str, Any]], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Split manifest exists: {path}. Pass --overwrite to replace.")
    doc_assignments: dict[str, str] = {}
    for fx in fixtures:
        doc_id = str(fx.get("source", {}).get("doc_id") or "").strip()
        split = str(fx.get("split") or "").strip()
        if not doc_id or not split:
            continue
        prev = doc_assignments.get(doc_id)
        if prev and prev != split:
            raise ValueError(f"Doc assigned to multiple splits: doc_id={doc_id}, {prev} vs {split}")
        doc_assignments[doc_id] = split

    split_counts = Counter(str(fx.get("split") or "") for fx in fixtures)
    manifest = {
        "version": "gold-fixture-splits-v1",
        "policy": {
            "split_unit": "doc_id",
            "no_doc_overlap": True,
            "required_splits": ["train", "val", "test", "holdout"],
            "stratify_by": ["category", "source_type"],
        },
        "counts": {
            "train": int(split_counts.get("train", 0)),
            "val": int(split_counts.get("val", 0)),
            "test": int(split_counts.get("test", 0)),
            "holdout": int(split_counts.get("holdout", 0)),
        },
        "doc_assignments": [
            {"doc_id": doc_id, "split": split}
            for doc_id, split in sorted(doc_assignments.items())
        ],
        "leakage_checks": {
            "doc_overlap_violations": 0,
            "fixture_overlap_violations": 0,
        },
        "notes": "Auto-generated by scripts/seed_gold_fixtures.py",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _validate_reason_codes(reason_codes_path: Path) -> set[str]:
    payload = _load_json(reason_codes_path)
    values = {
        str(item.get("code") or "").strip()
        for item in list(payload.get("codes") or [])
        if str(item.get("code") or "").strip()
    }
    if not values:
        raise ValueError(f"No reason codes found in {reason_codes_path}")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed v1 gold fixtures from corpus hotspots.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to corpus DuckDB")
    parser.add_argument("--out", type=Path, default=DEFAULT_FIXTURES, help="Output fixtures JSONL")
    parser.add_argument("--splits-out", type=Path, default=DEFAULT_SPLITS, help="Output split manifest JSON")
    parser.add_argument("--reason-codes", type=Path, default=DEFAULT_REASON_CODES, help="Reason-code taxonomy JSON")
    parser.add_argument("--run-manifest", type=Path, default=DEFAULT_RUN_MANIFEST, help="Corpus run manifest for snapshot id")
    parser.add_argument("--limit", type=int, default=100, help="Total fixtures to generate")
    parser.add_argument("--pool-multiplier", type=int, default=6, help="Candidate oversampling multiplier per category")
    parser.add_argument(
        "--quota-profile",
        choices=sorted(QUOTA_PROFILES.keys()),
        default="default",
        help="Category quota profile",
    )
    parser.add_argument("--cohort-only", action="store_true", help="Limit to cohort_included documents")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output files")
    args = parser.parse_args()

    if args.limit <= 0:
        raise ValueError("--limit must be > 0")
    if args.pool_multiplier <= 0:
        raise ValueError("--pool-multiplier must be > 0")

    valid_reason_codes = _validate_reason_codes(args.reason_codes)
    snapshot_id = _snapshot_id(args.run_manifest)

    conn = duckdb.connect(str(args.db), read_only=True)
    specs = _category_specs(args.quota_profile)

    total_quota = sum(int(s["quota"]) for s in specs)
    scale = float(args.limit) / float(total_quota) if total_quota > 0 else 1.0
    quotas = {
        s["category"]: max(1, int(round(int(s["quota"]) * scale)))
        for s in specs
    }
    # Correct rounding drift exactly to requested limit.
    while sum(quotas.values()) > args.limit:
        k = max(quotas, key=lambda x: quotas[x])
        quotas[k] -= 1
    while sum(quotas.values()) < args.limit:
        k = min(quotas, key=lambda x: quotas[x])
        quotas[k] += 1

    fixtures: list[dict[str, Any]] = []
    used_sections: set[tuple[str, str]] = set()
    fixture_counter = 1

    for spec in specs:
        category = str(spec["category"])
        quota = quotas[category]
        candidates = _fetch_candidates(
            conn,
            str(spec["sql"]),
            cohort_only=args.cohort_only,
            limit=quota * args.pool_multiplier,
        )

        taken = 0
        for doc_id, section_number, score in candidates:
            key = (doc_id, section_number)
            if key in used_sections:
                continue
            fixture_id = f"GFV1-{category.upper().replace('-', '_')}-{fixture_counter:04d}"
            fixture = _fixture_for_section(
                conn,
                fixture_id=fixture_id,
                spec=spec,
                doc_id=doc_id,
                section_number=section_number,
                score=score,
                snapshot_id=snapshot_id,
            )
            if fixture is None:
                continue
            bad_codes = [c for c in fixture["reason_codes"] if c not in valid_reason_codes]
            if bad_codes:
                raise ValueError(f"Unknown reason codes in fixture {fixture_id}: {bad_codes}")
            fixtures.append(fixture)
            used_sections.add(key)
            fixture_counter += 1
            taken += 1
            if taken >= quota:
                break

    # Backfill if any category could not meet quota.
    if len(fixtures) < args.limit:
        need = args.limit - len(fixtures)
        fallback_spec = next(s for s in specs if s["category"] == "linking_contract")
        fallback_candidates = _fetch_candidates(
            conn,
            str(fallback_spec["sql"]),
            cohort_only=args.cohort_only,
            limit=need * args.pool_multiplier,
        )
        for doc_id, section_number, score in fallback_candidates:
            if len(fixtures) >= args.limit:
                break
            key = (doc_id, section_number)
            if key in used_sections:
                continue
            fixture_id = f"GFV1-{fallback_spec['category'].upper().replace('-', '_')}-{fixture_counter:04d}"
            fixture = _fixture_for_section(
                conn,
                fixture_id=fixture_id,
                spec=fallback_spec,
                doc_id=doc_id,
                section_number=section_number,
                score=score,
                snapshot_id=snapshot_id,
            )
            if fixture is None:
                continue
            fixtures.append(fixture)
            used_sections.add(key)
            fixture_counter += 1

    conn.close()

    if len(fixtures) != args.limit:
        raise RuntimeError(f"Expected {args.limit} fixtures but generated {len(fixtures)}")

    _write_jsonl(args.out, fixtures, overwrite=args.overwrite)
    _write_split_manifest(args.splits_out, fixtures, overwrite=args.overwrite)

    cat_counts = Counter(str(fx.get("category") or "") for fx in fixtures)
    decision_counts = Counter(str(fx.get("gold_decision") or "") for fx in fixtures)
    split_counts = Counter(str(fx.get("split") or "") for fx in fixtures)
    print(json.dumps(
        {
            "status": "ok",
            "fixtures_written": len(fixtures),
            "out": str(args.out),
            "splits_out": str(args.splits_out),
            "quota_profile": args.quota_profile,
            "snapshot_id": snapshot_id,
            "category_counts": dict(sorted(cat_counts.items())),
            "decision_counts": dict(sorted(decision_counts.items())),
            "split_counts": dict(sorted(split_counts.items())),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
