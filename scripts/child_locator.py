#!/usr/bin/env python3
"""Find child patterns within parent sections using clause-level AST.

Usage:
    python3 scripts/child_locator.py --db corpus_index/corpus.duckdb \\
      --parent-matches parent_hits.json \\
      --child-keywords "leverage ratio,ratio debt" \\
      --auto-unroll

Outputs structured JSON to stdout, human messages to stderr.
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent.corpus import SchemaVersionError, ensure_schema_version
from agent.preemption import extract_preemption_edges, summarize_preemption
from agent.scope_parity import compute_scope_parity

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def load_json(path: Path) -> object:
        return orjson.loads(path.read_bytes())
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def load_json(path: Path) -> object:
        with open(path) as f:
            return json.load(f)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def heading_matches(header_text: str, patterns: list[str]) -> tuple[bool, float]:
    """Check if a header matches any of the heading patterns."""
    if not header_text or not patterns:
        return False, 0.0

    header_lower = header_text.lower().strip()
    best_score = 0.0

    for pattern in patterns:
        pattern_lower = pattern.lower().strip()
        if not pattern_lower:
            continue

        # Exact match
        if header_lower == pattern_lower:
            return True, 1.0

        # Substring match
        if pattern_lower in header_lower:
            score = len(pattern_lower) / len(header_lower)
            best_score = max(best_score, min(score + 0.3, 0.95))

        # Word-level match
        pattern_words = set(pattern_lower.split())
        header_words = set(header_lower.split())
        if pattern_words and pattern_words.issubset(header_words):
            score = len(pattern_words) / len(header_words)
            best_score = max(best_score, min(score + 0.2, 0.90))

    if best_score >= 0.5:
        return True, best_score
    return False, best_score


def keyword_density(text: str, keywords: list[str]) -> tuple[bool, float]:
    """Check if text contains keywords, return match status and density score."""
    if not text or not keywords:
        return False, 0.0

    text_lower = text.lower()
    matched_count = 0
    total_hits = 0

    for kw in keywords:
        kw_lower = kw.lower().strip()
        if not kw_lower:
            continue
        count = len(re.findall(re.escape(kw_lower), text_lower))
        if count > 0:
            matched_count += 1
            total_hits += count

    if matched_count == 0:
        return False, 0.0

    # Score based on fraction of keywords matched and density
    keyword_coverage = matched_count / len(keywords)
    density = min(total_hits / max(len(text_lower.split()), 1), 1.0)
    score = 0.6 * keyword_coverage + 0.4 * density
    return True, min(score, 1.0)


def extract_defined_terms(text: str) -> list[dict]:
    """Extract defined terms from clause text using regex patterns."""
    results: list[dict] = []
    patterns = [
        re.compile(
            r'"([^"]{2,80})"\s+(?:means?|shall\s+mean)',
            re.IGNORECASE,
        ),
        re.compile(
            r'\u201c([^\u201d]{2,80})\u201d\s+(?:means?|shall\s+mean)',
            re.IGNORECASE,
        ),
    ]

    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            term = match.group(1)
            if term.lower() not in seen:
                seen.add(term.lower())
                # Get surrounding text as definition snippet
                end = min(match.end() + 200, len(text))
                snippet = text[match.start():end].strip()
                results.append({"term": term, "text": snippet, "source": ""})

    return results


def _as_int(value: object) -> int | None:
    """Best-effort integer conversion for DB values."""
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _derive_clause_text(
    section_text: str,
    *,
    span_start: object,
    span_end: object,
    section_char_start: object,
) -> str:
    """Derive clause text from section text and spans.

    Primary path assumes global spans:
        rel = span - section_char_start
    Fallback path assumes section-relative spans.
    """
    if not section_text:
        return ""
    start = _as_int(span_start)
    end = _as_int(span_end)
    if start is None or end is None or end <= start:
        return ""

    candidates: list[tuple[int, int]] = []
    sec_start = _as_int(section_char_start)
    if sec_start is not None:
        candidates.append((start - sec_start, end - sec_start))
    candidates.append((start, end))

    for rel_start, rel_end in candidates:
        if 0 <= rel_start < rel_end <= len(section_text):
            return section_text[rel_start:rel_end]
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find child patterns within parent sections."
    )
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument(
        "--parent-matches",
        required=True,
        help="JSON file with parent match results (list of {doc_id, section_number})",
    )
    parser.add_argument(
        "--child-keywords",
        default=None,
        help="Comma-separated keywords to search in clauses",
    )
    parser.add_argument(
        "--child-headings",
        default=None,
        help="Comma-separated heading patterns for clause headers",
    )
    parser.add_argument(
        "--auto-unroll",
        action="store_true",
        help="Append linked definitions for found clauses",
    )
    parser.add_argument(
        "--min-depth", type=int, default=1, help="Minimum clause depth to search"
    )
    parser.add_argument(
        "--max-depth", type=int, default=4, help="Maximum clause depth to search"
    )
    parser.add_argument(
        "--scope-parity-allow",
        default=None,
        help="Comma-separated allowed parity labels (e.g., NARROW,BALANCED).",
    )
    parser.add_argument(
        "--min-operator-count",
        type=int,
        default=0,
        help="Minimum boolean operator count in matched clause.",
    )
    parser.add_argument(
        "--require-both-operator-types",
        action="store_true",
        help="Require both permit and restrict operators.",
    )
    parser.add_argument(
        "--require-preemption",
        action="store_true",
        help="Require at least one preemption marker (override/yield).",
    )
    parser.add_argument(
        "--min-override-count",
        type=int,
        default=0,
        help="Minimum override marker count (e.g., notwithstanding).",
    )
    parser.add_argument(
        "--min-yield-count",
        type=int,
        default=0,
        help="Minimum yield marker count (e.g., subject to).",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    parser.add_argument(
        "--emit-not-found",
        action="store_true",
        help="Emit NOT_FOUND rows for parent matches with no child clause match.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run identifier for provenance; auto-generated when omitted.",
    )
    parser.add_argument(
        "--strategy-version",
        type=int,
        default=None,
        help="Optional strategy version for provenance fields.",
    )
    parser.add_argument(
        "--ontology-node-id",
        default="",
        help="Optional ontology node id for provenance fields.",
    )
    args = parser.parse_args()
    run_id = args.run_id or (
        f"child_locator_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    )

    db_path = Path(args.db)
    if not db_path.exists():
        log(f"Error: database not found at {db_path}")
        sys.exit(1)

    parent_path = Path(args.parent_matches)
    if not parent_path.exists():
        log(f"Error: parent matches file not found at {parent_path}")
        sys.exit(1)

    keywords = (
        [k.strip() for k in args.child_keywords.split(",") if k.strip()]
        if args.child_keywords
        else []
    )
    headings = (
        [h.strip() for h in args.child_headings.split(",") if h.strip()]
        if args.child_headings
        else []
    )
    parity_allow = {
        p.strip().upper()
        for p in (args.scope_parity_allow.split(",") if args.scope_parity_allow else [])
        if p.strip()
    }

    if not keywords and not headings:
        log("Warning: no --child-keywords or --child-headings specified. "
            "Will return all clauses in depth range.")

    try:
        import duckdb
    except ImportError:
        log("Error: duckdb package is required. Install with: pip install duckdb")
        sys.exit(1)

    # Load parent matches
    parent_matches = load_json(parent_path)
    if not isinstance(parent_matches, list):
        log("Error: parent matches must be a JSON array")
        sys.exit(1)

    log(f"Loaded {len(parent_matches)} parent match(es)")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        ensure_schema_version(con, db_path=db_path)
    except SchemaVersionError as exc:
        log(f"Error: {exc}")
        con.close()
        sys.exit(1)

    # Discover schema
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    log(f"Available tables: {tables}")

    # Find clauses table
    clauses_table = None
    for candidate in ["clauses", "clause", "sections", "paragraphs", "content"]:
        if candidate in tables:
            clauses_table = candidate
            break

    if not clauses_table:
        log(f"Error: no clauses table found. Available: {tables}")
        con.close()
        sys.exit(1)

    columns_info = con.execute(
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{clauses_table}'"
    ).fetchall()
    columns = [row[0] for row in columns_info]
    log(f"Using table '{clauses_table}' with columns: {columns}")

    # Map column names
    doc_id_col = next(
        (c for c in columns if c in ("doc_id", "document_id")), None
    )
    section_col = next(
        (c for c in columns if c in ("section_number", "section_id", "section", "parent_section")),
        None,
    )
    text_col = next(
        (c for c in columns if c in ("text", "content", "body", "clause_text", "section_text")),
        None,
    )
    header_col = next(
        (c for c in columns if c in ("header_text", "heading", "title", "header")),
        None,
    )
    depth_col = next(
        (c for c in columns if c in ("depth", "level", "clause_depth")), None
    )
    clause_id_col = next(
        (c for c in columns if c in ("clause_id", "clause_number", "id", "paragraph_id")),
        None,
    )
    label_col = next(
        (c for c in columns if c in ("label", "clause_label", "numbering")), None
    )
    path_col = next(
        (c for c in columns if c in ("clause_path", "path", "full_path")), None
    )
    start_col = next(
        (c for c in columns if c in ("span_start", "char_start", "start_offset")),
        None,
    )
    end_col = next(
        (c for c in columns if c in ("span_end", "char_end", "end_offset")), None
    )

    if not doc_id_col:
        log(f"Error: no doc_id column found in {clauses_table}")
        con.close()
        sys.exit(1)

    template_by_doc: dict[str, str] = {}
    if "documents" in tables:
        doc_cols_info = con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'"
        ).fetchall()
        doc_cols = {row[0] for row in doc_cols_info}
        if "doc_id" in doc_cols and "template_family" in doc_cols:
            parent_doc_ids = sorted(
                {
                    str(parent.get("doc_id", "")).strip()
                    for parent in parent_matches
                    if str(parent.get("doc_id", "")).strip()
                }
            )
            for pid in parent_doc_ids:
                row = con.execute(
                    "SELECT template_family FROM documents WHERE doc_id = ?",
                    [pid],
                ).fetchone()
                template_by_doc[pid] = str(row[0] or "") if row else ""

    has_section_text = "section_text" in tables
    has_sections = "sections" in tables
    needs_derived_clause_text = text_col is None

    if needs_derived_clause_text and (keywords or args.auto_unroll):
        if not has_section_text:
            log(
                "Error: clauses table has no text column and section_text table is unavailable; "
                "cannot run keyword matching or auto-unroll."
            )
            con.close()
            sys.exit(1)
        if section_col is None or start_col is None or end_col is None:
            log(
                "Error: missing section/span columns required to derive clause text "
                "(need section_number + span_start + span_end)."
            )
            con.close()
            sys.exit(1)

    cohort_filter_sql = ""
    if not args.include_all and "documents" in tables:
        docs_cols_info = con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'"
        ).fetchall()
        docs_cols = {row[0] for row in docs_cols_info}
        if "cohort_included" in docs_cols:
            cohort_filter_sql = (
                " AND c."
                + str(doc_id_col)
                + " IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
            )
        else:
            log(
                "Warning: documents.cohort_included column missing; "
                "cannot enforce cohort-only filter."
            )

    results: list[dict] = []

    for parent in parent_matches:
        p_doc_id = parent.get("doc_id")
        p_section = parent.get("section_number")

        if not p_doc_id:
            log(f"Warning: skipping parent match without doc_id: {parent}")
            continue
        template_family = template_by_doc.get(str(p_doc_id), "")
        matched_for_parent = 0

        # Build query
        where_parts = [f"c.{doc_id_col} = ?"]
        params: list[object] = [p_doc_id]

        if p_section and section_col:
            where_parts.append(f"c.{section_col} = ?")
            params.append(p_section)

        if depth_col:
            where_parts.append(f"c.{depth_col} >= ?")
            params.append(args.min_depth)
            where_parts.append(f"c.{depth_col} <= ?")
            params.append(args.max_depth)

        where_clause = " AND ".join(where_parts) + cohort_filter_sql
        select_parts = ["c.*"]
        join_sql = ""
        if needs_derived_clause_text and section_col:
            select_parts.append("st.text AS __section_text")
            join_sql += (
                f" LEFT JOIN section_text st "
                f"ON c.{doc_id_col} = st.doc_id AND c.{section_col} = st.section_number"
            )
            if has_sections:
                select_parts.append("s.char_start AS __section_char_start")
                join_sql += (
                    f" LEFT JOIN sections s "
                    f"ON c.{doc_id_col} = s.doc_id AND c.{section_col} = s.section_number"
                )

        query = (
            f"SELECT {', '.join(select_parts)} FROM {clauses_table} c"
            f"{join_sql} WHERE {where_clause}"
        )

        rows = con.execute(query, params).fetchall()
        col_names = [desc[0] for desc in con.description]

        for row in rows:
            record = dict(zip(col_names, row, strict=True))

            clause_text = record.get(text_col, "") if text_col else ""
            if (not clause_text) and needs_derived_clause_text:
                clause_text = _derive_clause_text(
                    str(record.get("__section_text", "") or ""),
                    span_start=record.get(start_col) if start_col else None,
                    span_end=record.get(end_col) if end_col else None,
                    section_char_start=record.get("__section_char_start"),
                )
            clause_header = record.get(header_col, "") if header_col else ""
            clause_text = clause_text or ""
            clause_header = clause_header or ""

            match_type = None
            match_score = 0.0

            # Check headings
            if headings and clause_header:
                h_match, h_score = heading_matches(clause_header, headings)
                if h_match:
                    match_type = "heading"
                    match_score = h_score

            # Check keywords
            if keywords and clause_text:
                k_match, k_score = keyword_density(clause_text, keywords)
                if k_match and (match_type is None or k_score > match_score):
                    match_type = "keyword"
                    match_score = k_score

            # If no filters specified, include everything
            if not keywords and not headings:
                match_type = "unfiltered"
                match_score = 1.0

            if match_type is None:
                continue

            parity = compute_scope_parity(str(clause_text))
            preemption_summary = summarize_preemption(str(clause_text))

            if parity_allow and parity.label.upper() not in parity_allow:
                continue
            if parity.operator_count < args.min_operator_count:
                continue
            if args.require_both_operator_types and (
                parity.permit_count <= 0 or parity.restrict_count <= 0
            ):
                continue
            if args.require_preemption and not preemption_summary.has_preemption:
                continue
            if preemption_summary.override_count < args.min_override_count:
                continue
            if preemption_summary.yield_count < args.min_yield_count:
                continue

            preemption_edges = extract_preemption_edges(str(clause_text))

            result_entry: dict = {
                "schema_version": "child_locator_v2",
                "record_type": "HIT",
                "run_id": run_id,
                "ontology_node_id": args.ontology_node_id,
                "strategy_version": args.strategy_version,
                "doc_id": p_doc_id,
                "template_family": template_family,
                "parent_section": p_section or "",
                "section_number": p_section or "",
                "clause_id": record.get(clause_id_col, "") if clause_id_col else "",
                "clause_path": record.get(path_col, "") if path_col else "",
                "clause_depth": record.get(depth_col, 0) if depth_col else 0,
                "label": record.get(label_col, "") if label_col else "",
                "header_text": clause_header,
                "heading": clause_header,
                "clause_text": clause_text,
                "span_start": record.get(start_col) if start_col else None,
                "span_end": record.get(end_col) if end_col else None,
                "char_start": record.get(start_col) if start_col else None,
                "char_end": record.get(end_col) if end_col else None,
                "match_type": match_type,
                "match_score": round(match_score, 4),
                "score": round(match_score, 4),
                "confidence_breakdown": {
                    "match_score": round(match_score, 4),
                    "source": "child_locator",
                },
                "outlier": {"level": "none", "score": 0.0, "flags": []},
                "scope_parity": {
                    "label": parity.label,
                    "permit_count": parity.permit_count,
                    "restrict_count": parity.restrict_count,
                    "operator_count": parity.operator_count,
                    "estimated_depth": parity.estimated_depth,
                },
                "preemption": {
                    "override_count": preemption_summary.override_count,
                    "yield_count": preemption_summary.yield_count,
                    "estimated_depth": preemption_summary.estimated_depth,
                    "has_preemption": preemption_summary.has_preemption,
                    "edge_count": preemption_summary.edge_count,
                    "edges": [
                        {
                            "edge_type": edge.edge_type,
                            "trigger_text": edge.trigger_text,
                            "reference": edge.reference,
                            "char_start": edge.char_start,
                            "char_end": edge.char_end,
                        }
                        for edge in preemption_edges
                    ],
                },
            }

            # Auto-unroll: find defined terms in clause text
            if args.auto_unroll and clause_text:
                unrolled = extract_defined_terms(clause_text)
                result_entry["unrolled_definitions"] = unrolled
            else:
                result_entry["unrolled_definitions"] = []

            results.append(result_entry)
            matched_for_parent += 1

        if args.emit_not_found and matched_for_parent == 0:
            results.append(
                {
                    "schema_version": "child_locator_v2",
                    "record_type": "NOT_FOUND",
                    "run_id": run_id,
                    "ontology_node_id": args.ontology_node_id,
                    "strategy_version": args.strategy_version,
                    "doc_id": p_doc_id,
                    "template_family": template_family,
                    "parent_section": p_section or "",
                    "section_number": p_section or "",
                    "clause_path": "",
                    "clause_depth": None,
                    "heading": "",
                    "header_text": "",
                    "clause_text": "",
                    "char_start": None,
                    "char_end": None,
                    "match_type": "not_found",
                    "match_score": 0.0,
                    "score": 0.0,
                    "confidence_breakdown": {
                        "match_score": 0.0,
                        "source": "child_locator",
                    },
                    "outlier": {"level": "none", "score": 0.0, "flags": []},
                    "scope_parity": {},
                    "preemption": {},
                    "unrolled_definitions": [],
                    "not_found_reason": "no_child_clause_match",
                }
            )

    con.close()

    log(f"Found {len(results)} child clause match(es) across {len(parent_matches)} parent(s)")
    dump_json(results)


if __name__ == "__main__":
    main()
