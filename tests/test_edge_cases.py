"""Tests for the expanded edge case inspector (38 categories, 6 tiers)."""
from __future__ import annotations

from typing import Any

import pytest

from dashboard.api.server import (
    _CATEGORY_TO_TIER,
    _EDGE_CASE_CATEGORIES,
    _EDGE_CASE_TIERS,
    _build_doc_category_queries,
    _build_iqr_category_queries,
    _build_join_category_queries,
    _get_tier,
)

try:
    import duckdb
except ImportError:
    pytest.skip("duckdb not installed", allow_module_level=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE documents (
    doc_id VARCHAR PRIMARY KEY,
    cik VARCHAR,
    accession VARCHAR,
    path VARCHAR,
    borrower VARCHAR DEFAULT '',
    admin_agent VARCHAR DEFAULT '',
    facility_size_mm DOUBLE,
    facility_confidence VARCHAR DEFAULT 'none',
    closing_ebitda_mm DOUBLE,
    ebitda_confidence VARCHAR DEFAULT 'none',
    closing_date DATE,
    filing_date DATE,
    form_type VARCHAR DEFAULT '',
    template_family VARCHAR DEFAULT '',
    doc_type VARCHAR DEFAULT 'other',
    doc_type_confidence VARCHAR DEFAULT 'low',
    market_segment VARCHAR DEFAULT 'uncertain',
    segment_confidence VARCHAR DEFAULT 'low',
    cohort_included BOOLEAN DEFAULT false,
    word_count INTEGER DEFAULT 0,
    section_count INTEGER DEFAULT 0,
    clause_count INTEGER DEFAULT 0,
    definition_count INTEGER DEFAULT 0,
    text_length INTEGER DEFAULT 0,
    section_parser_mode VARCHAR DEFAULT '',
    section_fallback_used BOOLEAN DEFAULT false
);

CREATE TABLE sections (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    heading VARCHAR,
    char_start INTEGER,
    char_end INTEGER,
    article_num INTEGER,
    word_count INTEGER,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE clauses (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    clause_id VARCHAR NOT NULL,
    label VARCHAR,
    depth INTEGER,
    level_type VARCHAR,
    span_start INTEGER,
    span_end INTEGER,
    header_text VARCHAR,
    clause_text VARCHAR,
    parent_id VARCHAR DEFAULT '',
    is_structural BOOLEAN DEFAULT true,
    parse_confidence DOUBLE DEFAULT 0.0,
    PRIMARY KEY (doc_id, section_number, clause_id)
);

CREATE TABLE definitions (
    doc_id VARCHAR NOT NULL,
    term VARCHAR NOT NULL,
    definition_text VARCHAR,
    char_start INTEGER,
    char_end INTEGER,
    pattern_engine VARCHAR,
    confidence DOUBLE DEFAULT 0.0,
    definition_type VARCHAR DEFAULT 'DIRECT',
    definition_types VARCHAR,
    type_confidence DOUBLE DEFAULT 0.0,
    type_signals VARCHAR,
    dependency_terms VARCHAR
);
"""


def _make_db() -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB with the corpus schema."""
    conn = duckdb.connect(":memory:")
    conn.execute(_SCHEMA_SQL)
    return conn


def _ins_doc(conn: duckdb.DuckDBPyConnection, **kw: Any) -> None:
    """Insert a document with given column overrides."""
    cols = list(kw.keys())
    vals = list(kw.values())
    placeholders = ", ".join(["?"] * len(vals))
    conn.execute(
        f"INSERT INTO documents ({', '.join(cols)}) "
        f"VALUES ({placeholders})",
        vals,
    )


def _ins_clause(
    conn: duckdb.DuckDBPyConnection,
    doc_id: str,
    sec: str,
    cid: str,
    *,
    depth: int = 1,
    level_type: str = "alpha",
    parent: str = "",
    structural: bool = True,
    conf: float = 0.9,
    span_start: int = 0,
) -> None:
    """Insert a clause row."""
    conn.execute(
        "INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            doc_id, sec, cid, f"({cid})", depth, level_type,
            span_start, span_start + 50, "", "",
            parent, structural, conf,
        ],
    )


class FakeCorpus:
    """Minimal stand-in for CorpusIndex."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def query(
        self, sql: str, params: list[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        if params:
            return self._conn.execute(sql, params).fetchall()
        return self._conn.execute(sql).fetchall()


def _run_all_queries(
    conn: duckdb.DuckDBPyConnection,
    cohort_where: str = "WHERE",
    cohort_only: bool = False,
) -> dict[str, list[tuple[Any, ...]]]:
    """Execute all category queries, return by category."""
    corpus = FakeCorpus(conn)
    parts: list[tuple[str, list[Any]]] = []
    parts.extend(_build_doc_category_queries(cohort_where))
    parts.extend(_build_join_category_queries(cohort_where))
    parts.extend(
        _build_iqr_category_queries(corpus, cohort_where, cohort_only),
    )
    results: dict[str, list[tuple[Any, ...]]] = {}
    for sql, params in parts:
        rows = (
            conn.execute(sql, params).fetchall()
            if params
            else conn.execute(sql).fetchall()
        )
        for row in rows:
            cat = str(row[2])
            results.setdefault(cat, []).append(row)
    return results


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


def test_tier_registry_completeness() -> None:
    all_cats = {
        cat for cats in _EDGE_CASE_TIERS.values() for cat in cats
    }
    assert all_cats == set(_CATEGORY_TO_TIER)
    assert all_cats | {"all"} == _EDGE_CASE_CATEGORIES


def test_tier_count() -> None:
    total = sum(len(c) for c in _EDGE_CASE_TIERS.values())
    assert total == 38
    assert len(_EDGE_CASE_TIERS) == 6


def test_get_tier() -> None:
    assert _get_tier("missing_sections") == "structural"
    assert _get_tier("low_definitions") == "definitions"
    assert _get_tier("extreme_facility") == "metadata"
    assert _get_tier("extreme_word_count") == "document"
    assert _get_tier("orphan_template") == "template"
    assert _get_tier("nonexistent") == "unknown"


# ---------------------------------------------------------------------------
# Original 5 categories — regression
# ---------------------------------------------------------------------------


def test_missing_sections() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="doc1", word_count=50000,
        section_count=0, doc_type="credit_agreement",
    )
    results = _run_all_queries(conn)
    assert "missing_sections" in results
    assert results["missing_sections"][0][0] == "doc1"
    assert results["missing_sections"][0][3] == "high"


def test_low_definitions() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="doc1", word_count=15000,
        definition_count=5, section_count=10,
    )
    results = _run_all_queries(conn)
    assert "low_definitions" in results
    assert len(results["low_definitions"]) == 1


def test_zero_clauses() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="doc1", word_count=20000,
        section_count=10, clause_count=0,
    )
    results = _run_all_queries(conn)
    assert "zero_clauses" in results


def test_extreme_facility() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="doc1",
        facility_size_mm=99999, word_count=10000,
    )
    results = _run_all_queries(conn)
    assert "extreme_facility" in results


# ---------------------------------------------------------------------------
# Clause depth anomaly tests (user priority)
# ---------------------------------------------------------------------------


def test_orphan_deep_clause() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        section_count=5, clause_count=10,
    )
    # 3-segment clause_id (tree_level=3) with parent that doesn't exist
    _ins_clause(
        conn, "d1", "1", "a.i.A",
        depth=3, level_type="caps", parent="nonexistent",
    )
    results = _run_all_queries(conn)
    assert "orphan_deep_clause" in results
    assert "orphaned" in str(results["orphan_deep_clause"][0][4])


def test_inconsistent_sibling_depth() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        section_count=5, clause_count=10,
    )
    # Siblings under same parent with different tree_levels (path lengths)
    _ins_clause(
        conn, "d1", "1", "p.child1",
        depth=2, level_type="roman", parent="p", span_start=101,
    )
    _ins_clause(
        conn, "d1", "1", "p.x.child2",
        depth=3, level_type="caps", parent="p", span_start=201,
    )
    results = _run_all_queries(conn)
    assert "inconsistent_sibling_depth" in results


def test_deep_nesting_outlier() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        section_count=5, clause_count=20,
    )
    # 5-segment clause_id → tree_level 5 (> 4 threshold)
    _ins_clause(
        conn, "d1", "1", "a.i.A.1.x",
        depth=1, level_type="alpha", parent="a.i.A.1", span_start=100,
    )
    results = _run_all_queries(conn)
    assert "deep_nesting_outlier" in results
    assert "tree level 5" in str(results["deep_nesting_outlier"][0][4]).lower()


def test_rootless_deep_clause() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        section_count=5, clause_count=10,
    )
    # tree_level > 1 (2-segment clause_id) but empty parent_id
    _ins_clause(
        conn, "d1", "1", "a.i",
        depth=2, level_type="roman", parent="", span_start=100,
    )
    results = _run_all_queries(conn)
    assert "rootless_deep_clause" in results
    assert "no parent link" in str(results["rootless_deep_clause"][0][4])


def test_low_structural_ratio() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        section_count=5, clause_count=20,
    )
    # 3 structural + 8 non-structural = 27%
    for i in range(3):
        _ins_clause(
            conn, "d1", "1", f"str{i}",
            structural=True, span_start=i * 100,
        )
    for i in range(8):
        _ins_clause(
            conn, "d1", "1", f"ns{i}",
            structural=False, span_start=300 + i * 100,
        )
    results = _run_all_queries(conn)
    assert "low_structural_ratio" in results


# ---------------------------------------------------------------------------
# New structural categories
# ---------------------------------------------------------------------------


def test_low_section_count() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=50000, section_count=3)
    results = _run_all_queries(conn)
    assert "low_section_count" in results


def test_section_fallback_used() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        section_count=10, section_fallback_used=True,
    )
    results = _run_all_queries(conn)
    assert "section_fallback_used" in results


def test_section_numbering_gap() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, section_count=5)
    # Sections 1, 2, 5 — gap between 2 and 5
    for sn, cs in [("1", 0), ("2", 100), ("5", 200)]:
        conn.execute(
            "INSERT INTO sections VALUES (?,?,?,?,?,?,?)",
            ["d1", sn, f"Section {sn}", cs, cs + 100, 1, 500],
        )
    results = _run_all_queries(conn)
    assert "section_numbering_gap" in results


def test_empty_section_headings() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, section_count=5)
    conn.execute(
        "INSERT INTO sections VALUES (?,?,?,?,?,?,?)",
        ["d1", "1", "", 0, 100, 1, 500],
    )
    conn.execute(
        "INSERT INTO sections VALUES (?,?,?,?,?,?,?)",
        ["d1", "2", None, 100, 200, 1, 500],
    )
    results = _run_all_queries(conn)
    assert "empty_section_headings" in results
    detail = str(results["empty_section_headings"][0][4])
    assert "2 sections" in detail


# ---------------------------------------------------------------------------
# New definition categories
# ---------------------------------------------------------------------------


def test_zero_definitions() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, definition_count=0)
    results = _run_all_queries(conn)
    assert "zero_definitions" in results


def test_high_definition_count() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=50000, definition_count=600)
    results = _run_all_queries(conn)
    assert "high_definition_count" in results


def test_duplicate_definitions() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, definition_count=50)
    conn.execute(
        "INSERT INTO definitions (doc_id, term, pattern_engine) "
        "VALUES ('d1', 'EBITDA', 'quoted')",
    )
    conn.execute(
        "INSERT INTO definitions (doc_id, term, pattern_engine) "
        "VALUES ('d1', 'EBITDA', 'parenthetical')",
    )
    results = _run_all_queries(conn)
    assert "duplicate_definitions" in results


def test_single_engine_definitions() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, definition_count=15)
    for i in range(15):
        conn.execute(
            "INSERT INTO definitions "
            "(doc_id, term, pattern_engine) "
            "VALUES (?, ?, ?)",
            ["d1", f"Term{i}", "quoted"],
        )
    results = _run_all_queries(conn)
    assert "single_engine_definitions" in results
    detail = str(results["single_engine_definitions"][0][4])
    assert "quoted" in detail


def test_definition_truncated_at_cap() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, definition_count=25)
    for i in range(5):
        conn.execute(
            "INSERT INTO definitions (doc_id, term, definition_text, pattern_engine) "
            "VALUES (?, ?, ?, ?)",
            ["d1", f"LongTerm{i}", "X" * 2000, "smart_quote"],
        )
    results = _run_all_queries(conn)
    assert "definition_truncated_at_cap" in results


def test_definition_signature_leak() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, definition_count=12)
    conn.execute(
        "INSERT INTO definitions (doc_id, term, definition_text, pattern_engine) "
        "VALUES (?, ?, ?, ?)",
        ["d1", "Authorized Signatory Title", "signature page language", "colon"],
    )
    results = _run_all_queries(conn)
    assert "definition_signature_leak" in results


def test_definition_malformed_term() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, definition_count=30)
    for i in range(20):
        conn.execute(
            "INSERT INTO definitions (doc_id, term, definition_text, pattern_engine) "
            "VALUES (?, ?, ?, ?)",
            ["d1", f"Bad\\nTerm{i}", "definition body", "colon"],
        )
    results = _run_all_queries(conn)
    assert "definition_malformed_term" in results


# ---------------------------------------------------------------------------
# New metadata categories
# ---------------------------------------------------------------------------


def test_missing_borrower() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, borrower="")
    results = _run_all_queries(conn)
    assert "missing_borrower" in results


def test_missing_facility_size() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, facility_size_mm=None)
    results = _run_all_queries(conn)
    assert "missing_facility_size" in results


def test_unknown_doc_type() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        doc_type="other", doc_type_confidence="low",
    )
    results = _run_all_queries(conn)
    assert "unknown_doc_type" in results


# ---------------------------------------------------------------------------
# New document quality categories
# ---------------------------------------------------------------------------


def test_short_text() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", text_length=5000, word_count=800)
    results = _run_all_queries(conn)
    assert "short_text" in results


def test_very_short_document() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=2000)
    results = _run_all_queries(conn)
    assert "very_short_document" in results


def test_extreme_text_ratio() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=10000, text_length=200000,
    )
    results = _run_all_queries(conn)
    assert "extreme_text_ratio" in results


# ---------------------------------------------------------------------------
# New template categories
# ---------------------------------------------------------------------------


def test_orphan_template() -> None:
    conn = _make_db()
    _ins_doc(conn, doc_id="d1", word_count=20000, template_family="")
    results = _run_all_queries(conn)
    assert "orphan_template" in results


def test_non_credit_agreement() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        doc_type="indenture", doc_type_confidence="high",
    )
    results = _run_all_queries(conn)
    assert "non_credit_agreement" in results


def test_non_cohort_large_doc() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=50000, cohort_included=False,
    )
    results = _run_all_queries(conn)
    assert "non_cohort_large_doc" in results


# ---------------------------------------------------------------------------
# IQR categories
# ---------------------------------------------------------------------------


def test_extreme_word_count_iqr() -> None:
    conn = _make_db()
    for i in range(20):
        _ins_doc(
            conn, doc_id=f"d{i}", word_count=48000 + i * 200,
        )
    _ins_doc(conn, doc_id="outlier", word_count=500)
    results = _run_all_queries(conn)
    if "extreme_word_count" in results:
        ids = {r[0] for r in results["extreme_word_count"]}
        assert "outlier" in ids


def test_excessive_section_count_iqr() -> None:
    conn = _make_db()
    for i in range(20):
        _ins_doc(
            conn, doc_id=f"d{i}",
            section_count=10 + i, word_count=50000,
        )
    _ins_doc(
        conn, doc_id="outlier",
        section_count=200, word_count=50000,
    )
    results = _run_all_queries(conn)
    if "excessive_section_count" in results:
        ids = {r[0] for r in results["excessive_section_count"]}
        assert "outlier" in ids


# ---------------------------------------------------------------------------
# Clause confidence
# ---------------------------------------------------------------------------


def test_low_avg_clause_confidence() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        section_count=5, clause_count=15,
    )
    for i in range(15):
        _ins_clause(
            conn, "d1", "1", f"c{i}",
            conf=0.2, span_start=i * 100,
        )
    results = _run_all_queries(conn)
    assert "low_avg_clause_confidence" in results


def test_clause_root_label_repeat_explosion() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=30000,
        section_count=5, clause_count=260,
    )
    for i in range(205):
        conn.execute(
            "INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                "d1", "1", f"ydup{i}", "(y)", 1, "alpha",
                i * 10, i * 10 + 5, "", "",
                "", True, 0.95,
            ],
        )
    results = _run_all_queries(conn)
    assert "clause_root_label_repeat_explosion" in results


def test_clause_dup_id_burst() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=30000,
        section_count=5, clause_count=260,
    )
    # 205 / 210 clause IDs include _dup => 97.6% dup ratio.
    for i in range(205):
        conn.execute(
            "INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                "d1", "1", f"a_dup{i}", "(a)", 1, "alpha",
                i * 10, i * 10 + 5, "", "",
                "", True, 0.9,
            ],
        )
    for i in range(5):
        conn.execute(
            "INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                "d1", "1", f"b{i}", "(b)", 1, "alpha",
                2050 + i * 10, 2055 + i * 10, "", "",
                "", True, 0.9,
            ],
        )
    results = _run_all_queries(conn)
    assert "clause_dup_id_burst" in results


def test_clause_depth_reset_after_deep() -> None:
    conn = _make_db()
    _ins_doc(
        conn, doc_id="d1", word_count=20000,
        section_count=5, clause_count=20,
    )
    conn.execute(
        "INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ["d1", "1", "a.i.A.1", "(1)", 4, "numeric", 100, 120, "", "", "a.i.A", True, 0.9],
    )
    conn.execute(
        "INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ["d1", "1", "y", "(y)", 1, "alpha", 130, 145, "", "", "", True, 0.9],
    )
    conn.execute(
        "INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ["d1", "1", "b.i.B.2", "(2)", 4, "numeric", 200, 220, "", "", "b.i.B", True, 0.9],
    )
    conn.execute(
        "INSERT INTO clauses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ["d1", "1", "z", "(z)", 1, "alpha", 230, 245, "", "", "", True, 0.9],
    )
    results = _run_all_queries(conn)
    assert "clause_depth_reset_after_deep" in results


# ---------------------------------------------------------------------------
# No false positives for well-formed document
# ---------------------------------------------------------------------------


def test_clean_document_no_edge_cases() -> None:
    """A well-formed doc should not trigger critical categories."""
    conn = _make_db()
    conn.execute(
        "INSERT INTO documents VALUES ("
        "  'clean', 'CIK', 'ACC', '/p', 'Borrower',"
        "  'Agent', 500.0, 'high', NULL, 'none',"
        "  '2024-01-15', '2024-01-10', '10-K',"
        "  'tmpl_a', 'credit_agreement', 'high',"
        "  'leveraged', 'high', true,"
        "  50000, 15, 200, 100, 300000, 'normal', false"
        ")"
    )
    for i in range(15):
        conn.execute(
            "INSERT INTO sections VALUES (?,?,?,?,?,?,?)",
            [
                "clean", str(i + 1), f"Section {i + 1}",
                i * 20000, (i + 1) * 20000, i + 1, 3000,
            ],
        )
    for i in range(100):
        _ins_clause(
            conn, "clean", str((i // 7) + 1), f"c{i}",
            depth=(i % 3) + 1, parent="root",
            conf=0.85, span_start=i * 100,
        )
    for i in range(100):
        eng = "quoted" if i % 2 == 0 else "parenthetical"
        conn.execute(
            "INSERT INTO definitions "
            "(doc_id, term, pattern_engine) VALUES (?,?,?)",
            ["clean", f"Term{i}", eng],
        )
    results = _run_all_queries(conn)
    critical = {
        "missing_sections", "zero_clauses",
        "zero_definitions", "very_short_document", "short_text",
        "definition_truncated_at_cap",
        "definition_signature_leak",
        "clause_root_label_repeat_explosion",
        "clause_dup_id_burst",
        "clause_depth_reset_after_deep",
    }
    for cat in critical:
        assert cat not in results, f"Flagged as {cat}"


# ---------------------------------------------------------------------------
# Builder function contract tests
# ---------------------------------------------------------------------------


def test_all_queries_valid_sql() -> None:
    """All SQL queries execute without error on empty tables."""
    conn = _make_db()
    corpus = FakeCorpus(conn)
    parts: list[tuple[str, list[Any]]] = []
    parts.extend(_build_doc_category_queries("WHERE"))
    parts.extend(_build_join_category_queries("WHERE"))
    parts.extend(_build_iqr_category_queries(corpus, "WHERE", False))
    for sql, params in parts:
        if params:
            conn.execute(sql, params).fetchall()
        else:
            conn.execute(sql).fetchall()


def test_union_all_executes() -> None:
    """Combined UNION ALL executes on empty tables."""
    conn = _make_db()
    corpus = FakeCorpus(conn)
    parts: list[tuple[str, list[Any]]] = []
    parts.extend(_build_doc_category_queries("WHERE"))
    parts.extend(_build_join_category_queries("WHERE"))
    parts.extend(_build_iqr_category_queries(corpus, "WHERE", False))
    all_q = [p[0] for p in parts]
    all_p: list[Any] = []
    for p in parts:
        all_p.extend(p[1])
    union = " UNION ALL ".join(all_q)
    rows = conn.execute(
        f"SELECT category, COUNT(*) FROM ({union}) "
        f"GROUP BY category",
        all_p,
    ).fetchall()
    assert isinstance(rows, list)
