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
from pathlib import Path

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
                start = match.start()
                end = min(match.end() + 200, len(text))
                snippet = text[match.start():end].strip()
                results.append({"term": term, "text": snippet, "source": ""})

    return results


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
    args = parser.parse_args()

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

    results: list[dict] = []

    for parent in parent_matches:
        p_doc_id = parent.get("doc_id")
        p_section = parent.get("section_number")

        if not p_doc_id:
            log(f"Warning: skipping parent match without doc_id: {parent}")
            continue

        # Build query
        where_parts = [f"{doc_id_col} = ?"]
        params: list[object] = [p_doc_id]

        if p_section and section_col:
            where_parts.append(f"{section_col} = ?")
            params.append(p_section)

        if depth_col:
            where_parts.append(f"{depth_col} >= ?")
            params.append(args.min_depth)
            where_parts.append(f"{depth_col} <= ?")
            params.append(args.max_depth)

        where_clause = " AND ".join(where_parts)
        query = f"SELECT * FROM {clauses_table} WHERE {where_clause}"

        rows = con.execute(query, params).fetchall()
        col_names = [desc[0] for desc in con.description]

        for row in rows:
            record = dict(zip(col_names, row))

            clause_text = record.get(text_col, "") if text_col else ""
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
                if k_match:
                    if match_type is None or k_score > match_score:
                        match_type = "keyword"
                        match_score = k_score

            # If no filters specified, include everything
            if not keywords and not headings:
                match_type = "unfiltered"
                match_score = 1.0

            if match_type is None:
                continue

            result_entry: dict = {
                "doc_id": p_doc_id,
                "parent_section": p_section or "",
                "clause_id": record.get(clause_id_col, "") if clause_id_col else "",
                "clause_path": record.get(path_col, "") if path_col else "",
                "clause_depth": record.get(depth_col, 0) if depth_col else 0,
                "label": record.get(label_col, "") if label_col else "",
                "header_text": clause_header,
                "span_start": record.get(start_col) if start_col else None,
                "span_end": record.get(end_col) if end_col else None,
                "match_type": match_type,
                "match_score": round(match_score, 4),
            }

            # Auto-unroll: find defined terms in clause text
            if args.auto_unroll and clause_text:
                unrolled = extract_defined_terms(clause_text)
                result_entry["unrolled_definitions"] = unrolled
            else:
                result_entry["unrolled_definitions"] = []

            results.append(result_entry)

    con.close()

    log(f"Found {len(results)} child clause match(es) across {len(parent_matches)} parent(s)")
    dump_json(results)


if __name__ == "__main__":
    main()
