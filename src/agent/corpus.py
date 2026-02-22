"""DuckDB-backed corpus index for credit agreement documents.

Provides read-only access to the pre-built corpus index (corpus.duckdb).
The index is built by scripts/build_corpus_index.py and opened read-only
by all CLI tools.

Tables:
    documents   — master index (one row per doc)
    sections    — section boundaries (FK to documents)
    clauses     — clause AST nodes (FK to sections)
    definitions — defined terms (FK to documents)
    section_text — full section text (lazy-loaded)
    _schema_version — schema version tracking
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Dynamic DuckDB import for pyright compatibility
_duckdb_mod = importlib.import_module("duckdb")


SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class DocRecord:
    """Summary record for a document in the corpus index."""

    doc_id: str
    cik: str
    accession: str
    path: str
    borrower: str
    admin_agent: str
    facility_size_mm: float | None
    closing_date: str | None
    filing_date: str | None
    form_type: str
    section_count: int
    clause_count: int
    definition_count: int
    text_length: int
    template_family: str


@dataclass(frozen=True, slots=True)
class SectionRecord:
    """A section in the corpus index."""

    doc_id: str
    section_number: str
    heading: str
    char_start: int
    char_end: int
    article_num: int
    word_count: int


@dataclass(frozen=True, slots=True)
class ClauseRecord:
    """A clause node in the corpus index."""

    doc_id: str
    section_number: str
    clause_id: str
    label: str
    depth: int
    level_type: str
    span_start: int
    span_end: int
    header_text: str
    parent_id: str
    is_structural: bool
    parse_confidence: float


@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    """A defined term in the corpus index."""

    doc_id: str
    term: str
    definition_text: str
    char_start: int
    char_end: int
    pattern_engine: str
    confidence: float


class CorpusIndex:
    """Read-only interface to the DuckDB corpus index.

    Opens the database in read-only mode. All queries return typed records.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: Any = _duckdb_mod.connect(str(db_path), read_only=True)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> CorpusIndex:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def schema_version(self) -> str:
        """Get the schema version of this corpus index."""
        try:
            result = self._conn.execute(
                "SELECT version FROM _schema_version WHERE table_name = 'corpus'"
            ).fetchone()
            return str(result[0]) if result else "unknown"
        except Exception:
            return "unknown"

    @property
    def doc_count(self) -> int:
        """Total number of documents in the index."""
        result = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        return int(result[0]) if result else 0

    def doc_ids(self) -> list[str]:
        """All document IDs, sorted."""
        rows = self._conn.execute(
            "SELECT doc_id FROM documents ORDER BY doc_id"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def get_doc(self, doc_id: str) -> DocRecord | None:
        """Get a document record by ID."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", [doc_id]
        ).fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in self._conn.description]
        d = dict(zip(cols, row))
        return DocRecord(
            doc_id=str(d.get("doc_id", "")),
            cik=str(d.get("cik", "")),
            accession=str(d.get("accession", "")),
            path=str(d.get("path", "")),
            borrower=str(d.get("borrower", "")),
            admin_agent=str(d.get("admin_agent", "")),
            facility_size_mm=float(d["facility_size_mm"]) if d.get("facility_size_mm") else None,
            closing_date=str(d["closing_date"]) if d.get("closing_date") else None,
            filing_date=str(d["filing_date"]) if d.get("filing_date") else None,
            form_type=str(d.get("form_type", "")),
            section_count=int(d.get("section_count", 0)),
            clause_count=int(d.get("clause_count", 0)),
            definition_count=int(d.get("definition_count", 0)),
            text_length=int(d.get("text_length", 0)),
            template_family=str(d.get("template_family", "")),
        )

    def search_sections(
        self,
        *,
        heading_pattern: str | None = None,
        article_num: int | None = None,
        doc_id: str | None = None,
        limit: int = 100,
    ) -> list[SectionRecord]:
        """Search sections by heading pattern, article number, or doc_id.

        Args:
            heading_pattern: SQL LIKE pattern for heading (e.g., '%Indebtedness%').
            article_num: Filter by article number.
            doc_id: Filter by document ID.
            limit: Maximum number of results.

        Returns:
            List of SectionRecord sorted by doc_id, section_number.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if heading_pattern:
            conditions.append("heading ILIKE ?")
            params.append(heading_pattern)
        if article_num is not None:
            conditions.append("article_num = ?")
            params.append(article_num)
        if doc_id:
            conditions.append("doc_id = ?")
            params.append(doc_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"""
            SELECT doc_id, section_number, heading, char_start, char_end,
                   article_num, word_count
            FROM sections
            WHERE {where}
            ORDER BY doc_id, char_start
            LIMIT ?
        """
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()

        return [
            SectionRecord(
                doc_id=str(r[0]), section_number=str(r[1]), heading=str(r[2]),
                char_start=int(r[3]), char_end=int(r[4]),
                article_num=int(r[5]), word_count=int(r[6]),
            )
            for r in rows
        ]

    def get_section_text(self, doc_id: str, section_number: str) -> str | None:
        """Get the full text of a section."""
        row = self._conn.execute(
            "SELECT text FROM section_text WHERE doc_id = ? AND section_number = ?",
            [doc_id, section_number],
        ).fetchone()
        return str(row[0]) if row else None

    def get_clauses(
        self,
        doc_id: str,
        section_number: str,
        *,
        structural_only: bool = False,
    ) -> list[ClauseRecord]:
        """Get clause nodes for a section."""
        query = """
            SELECT doc_id, section_number, clause_id, label, depth, level_type,
                   span_start, span_end, header_text, parent_id,
                   is_structural, parse_confidence
            FROM clauses
            WHERE doc_id = ? AND section_number = ?
        """
        params: list[Any] = [doc_id, section_number]
        if structural_only:
            query += " AND is_structural = true"
        query += " ORDER BY span_start"

        rows = self._conn.execute(query, params).fetchall()
        return [
            ClauseRecord(
                doc_id=str(r[0]), section_number=str(r[1]), clause_id=str(r[2]),
                label=str(r[3]), depth=int(r[4]), level_type=str(r[5]),
                span_start=int(r[6]), span_end=int(r[7]), header_text=str(r[8]),
                parent_id=str(r[9]), is_structural=bool(r[10]),
                parse_confidence=float(r[11]),
            )
            for r in rows
        ]

    def get_definitions(
        self,
        doc_id: str,
        *,
        term: str | None = None,
    ) -> list[DefinitionRecord]:
        """Get defined terms for a document."""
        if term:
            rows = self._conn.execute(
                """SELECT doc_id, term, definition_text, char_start, char_end,
                          pattern_engine, confidence
                   FROM definitions
                   WHERE doc_id = ? AND term ILIKE ?
                   ORDER BY char_start""",
                [doc_id, term],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT doc_id, term, definition_text, char_start, char_end,
                          pattern_engine, confidence
                   FROM definitions
                   WHERE doc_id = ?
                   ORDER BY char_start""",
                [doc_id],
            ).fetchall()

        return [
            DefinitionRecord(
                doc_id=str(r[0]), term=str(r[1]), definition_text=str(r[2]),
                char_start=int(r[3]), char_end=int(r[4]),
                pattern_engine=str(r[5]), confidence=float(r[6]),
            )
            for r in rows
        ]

    def search_text(
        self,
        pattern: str,
        *,
        context_chars: int = 200,
        max_results: int = 50,
        doc_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search across section text.

        Args:
            pattern: Search pattern (SQL LIKE with % wildcards).
            context_chars: Number of context characters to return.
            max_results: Maximum number of results.
            doc_ids: Optional list of doc_ids to restrict search to.

        Returns:
            List of dicts with doc_id, section_number, matched text, context.
        """
        conditions = ["text ILIKE ?"]
        params: list[Any] = [f"%{pattern}%"]

        if doc_ids:
            placeholders = ",".join(["?"] * len(doc_ids))
            conditions.append(f"doc_id IN ({placeholders})")
            params.extend(doc_ids)

        where = " AND ".join(conditions)
        query = f"""
            SELECT st.doc_id, st.section_number, st.text,
                   s.heading, s.article_num
            FROM section_text st
            JOIN sections s ON st.doc_id = s.doc_id
                           AND st.section_number = s.section_number
            WHERE {where}
            LIMIT ?
        """
        params.append(max_results)
        rows = self._conn.execute(query, params).fetchall()

        results: list[dict[str, Any]] = []
        pattern_lower = pattern.lower()
        for r in rows:
            text = str(r[2])
            text_lower = text.lower()
            pos = text_lower.find(pattern_lower)
            if pos < 0:
                continue
            ctx_start = max(0, pos - context_chars)
            ctx_end = min(len(text), pos + len(pattern) + context_chars)
            results.append({
                "doc_id": str(r[0]),
                "section_number": str(r[1]),
                "heading": str(r[3]),
                "article_num": int(r[4]),
                "char_offset": pos,
                "matched_text": text[pos:pos + len(pattern)],
                "context_before": text[ctx_start:pos],
                "context_after": text[pos + len(pattern):ctx_end],
            })

        return results

    def query(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        """Execute a raw SQL query against the corpus index.

        For advanced queries that don't fit the typed API.
        """
        if params:
            return self._conn.execute(sql, params).fetchall()
        return self._conn.execute(sql).fetchall()

    def sample_docs(
        self,
        n: int,
        *,
        seed: int = 42,
        stratify_by: str | None = None,
    ) -> list[str]:
        """Select a random sample of document IDs.

        Args:
            n: Number of documents to sample.
            seed: Random seed for reproducibility.
            stratify_by: Column to stratify by (e.g., 'template_family').

        Returns:
            List of doc_id strings.
        """
        if stratify_by:
            # Stratified: proportional allocation across groups
            query = f"""
                SELECT doc_id FROM (
                    SELECT doc_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY {stratify_by}
                               ORDER BY hash(doc_id || ?) % 1000000
                           ) as rn,
                           COUNT(*) OVER (PARTITION BY {stratify_by}) as group_size,
                           COUNT(*) OVER () as total_size
                    FROM documents
                ) sub
                WHERE rn <= GREATEST(1, CAST(? * group_size / total_size AS INTEGER))
                LIMIT ?
            """
            rows = self._conn.execute(query, [seed, n, n]).fetchall()
        else:
            query = """
                SELECT doc_id FROM documents
                ORDER BY hash(doc_id || ?) % 1000000
                LIMIT ?
            """
            rows = self._conn.execute(query, [seed, n]).fetchall()

        return [str(r[0]) for r in rows]
