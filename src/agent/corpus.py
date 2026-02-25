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
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.run_manifest import default_manifest_path_for_db, load_manifest

# Dynamic DuckDB import for pyright compatibility
_duckdb_mod = importlib.import_module("duckdb")


SCHEMA_VERSION = "0.2.0"


class SchemaVersionError(RuntimeError):
    """Raised when a corpus DB schema version does not match expected."""


def _read_schema_version(conn: Any) -> str:
    """Read corpus schema version from an open DuckDB connection."""
    try:
        result = conn.execute(
            "SELECT version FROM _schema_version WHERE table_name = 'corpus'"
        ).fetchone()
        return str(result[0]) if result else "unknown"
    except Exception:
        return "unknown"


def ensure_schema_version(
    conn: Any,
    *,
    db_path: Path | None = None,
    expected: str = SCHEMA_VERSION,
) -> str:
    """Validate schema version for an open DuckDB connection.

    Returns actual schema version on success.
    Raises SchemaVersionError on mismatch.
    """
    actual = _read_schema_version(conn)
    if actual != expected:
        where = f" in {db_path}" if db_path is not None else ""
        raise SchemaVersionError(
            f"Schema version mismatch{where}: expected {expected}, got {actual}"
        )
    return actual


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
    facility_confidence: str
    closing_ebitda_mm: float | None
    ebitda_confidence: str
    closing_date: str | None
    filing_date: str | None
    form_type: str
    section_count: int
    clause_count: int
    definition_count: int
    text_length: int
    template_family: str
    doc_type: str
    doc_type_confidence: str
    market_segment: str
    segment_confidence: str
    cohort_included: bool
    word_count: int


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
class ArticleRecord:
    """An article-level record in the corpus index."""

    doc_id: str
    article_num: int
    label: str
    title: str
    concept: str | None
    char_start: int
    char_end: int
    is_synthetic: bool


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
    definition_type: str = "DIRECT"
    definition_types: tuple[str, ...] = ()
    type_confidence: float = 0.0
    type_signals: tuple[str, ...] = ()
    dependency_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SectionFeatureRecord:
    """Materialized section-level features for fast evaluation."""

    doc_id: str
    section_number: str
    article_num: int
    char_start: int
    char_end: int
    word_count: int
    char_count: int
    heading_lower: str
    scope_label: str
    scope_operator_count: int
    scope_permit_count: int
    scope_restrict_count: int
    scope_estimated_depth: int
    preemption_override_count: int
    preemption_yield_count: int
    preemption_estimated_depth: int
    preemption_has: bool
    preemption_edge_count: int
    definition_types: tuple[str, ...]
    definition_type_primary: str
    definition_type_confidence: float


@dataclass(frozen=True, slots=True)
class ClauseFeatureRecord:
    """Materialized clause-level features for fast evaluation."""

    doc_id: str
    section_number: str
    clause_id: str
    depth: int
    level_type: str
    token_count: int
    char_count: int
    has_digits: bool
    parse_confidence: float
    is_structural: bool


def _decode_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(v) for v in value if str(v))
    if isinstance(value, list):
        return tuple(str(v) for v in value if str(v))
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ()
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return tuple(part.strip() for part in raw.split(",") if part.strip())
        if isinstance(decoded, list):
            return tuple(str(v) for v in decoded if str(v))
        return ()
    return ()


def load_candidate_doc_ids(path: Path) -> list[str]:
    """Load candidate doc IDs from txt/json payload and preserve order.

    Supported payload formats:
    - newline-delimited text (".txt", ".lst", or fallback when JSON parsing fails)
    - JSON list of doc IDs
    - JSON object containing either:
      - "doc_ids": [...]
      - "candidates": [{"doc_id": ...}, ...] or ["doc1", "doc2", ...]
    """
    text = path.read_text()
    suffix = path.suffix.lower()
    values: list[str]

    if suffix in {".txt", ".lst"}:
        values = [line.strip() for line in text.splitlines() if line.strip()]
    else:
        payload: Any
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: treat as newline-delimited text.
            values = [line.strip() for line in text.splitlines() if line.strip()]
        else:
            if isinstance(payload, list):
                values = [str(v).strip() for v in payload]
            elif isinstance(payload, dict):
                if isinstance(payload.get("doc_ids"), list):
                    values = [str(v).strip() for v in payload["doc_ids"]]
                elif isinstance(payload.get("candidates"), list):
                    values = [
                        str(row.get("doc_id", "")).strip()
                        if isinstance(row, dict)
                        else str(row).strip()
                        for row in payload["candidates"]
                    ]
                else:
                    values = []
            else:
                values = []

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


class CorpusIndex:
    """Read-only interface to the DuckDB corpus index.

    Opens the database in read-only mode. All queries return typed records.
    """

    def __init__(self, db_path: Path, *, enforce_schema: bool = True) -> None:
        self._db_path = db_path
        self._conn: Any = _duckdb_mod.connect(str(db_path), read_only=True)
        try:
            rows = self._conn.execute("SHOW TABLES").fetchall()
            self._table_names = {str(r[0]) for r in rows}
        except Exception:
            self._table_names = set()
        if enforce_schema:
            try:
                ensure_schema_version(self._conn, db_path=db_path)
            except Exception:
                self._conn.close()
                raise

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
        return _read_schema_version(self._conn)

    @property
    def run_manifest_path(self) -> Path:
        """Canonical run-manifest path sidecar for this DB."""
        return default_manifest_path_for_db(self._db_path)

    def get_run_manifest(
        self,
        manifest_path: Path | None = None,
    ) -> dict[str, Any] | None:
        """Load run manifest from sidecar JSON if available.

        Args:
            manifest_path: Optional explicit path. Defaults to sidecar path.

        Returns:
            Parsed manifest dict, or None when manifest file does not exist.
        """
        path = manifest_path.resolve() if manifest_path else self.run_manifest_path
        if not path.exists():
            return None
        payload = load_manifest(path)
        return payload

    @property
    def doc_count(self) -> int:
        """Total number of documents in the index."""
        result = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        return int(result[0]) if result else 0

    def cohort_count(self) -> int:
        """Number of cohort-included documents (leveraged CAs)."""
        result = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE cohort_included = true"
        ).fetchone()
        return int(result[0]) if result else 0

    def doc_ids(self, *, cohort_only: bool = True) -> list[str]:
        """All document IDs, sorted.

        Args:
            cohort_only: If True, only return cohort-included documents.
        """
        where = " WHERE cohort_included = true" if cohort_only else ""
        rows = self._conn.execute(
            f"SELECT doc_id FROM documents{where} ORDER BY doc_id"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def _doc_from_row(self, d: dict[str, Any]) -> DocRecord:
        """Build a DocRecord from a column-name → value dict."""
        return DocRecord(
            doc_id=str(d.get("doc_id", "")),
            cik=str(d.get("cik", "")),
            accession=str(d.get("accession", "")),
            path=str(d.get("path", "")),
            borrower=str(d.get("borrower", "")),
            admin_agent=str(d.get("admin_agent", "")),
            facility_size_mm=float(d["facility_size_mm"]) if d.get("facility_size_mm") else None,
            facility_confidence=str(d.get("facility_confidence", "none")),
            closing_ebitda_mm=float(d["closing_ebitda_mm"]) if d.get("closing_ebitda_mm") else None,
            ebitda_confidence=str(d.get("ebitda_confidence", "none")),
            closing_date=str(d["closing_date"]) if d.get("closing_date") else None,
            filing_date=str(d["filing_date"]) if d.get("filing_date") else None,
            form_type=str(d.get("form_type", "")),
            section_count=int(d.get("section_count", 0)),
            clause_count=int(d.get("clause_count", 0)),
            definition_count=int(d.get("definition_count", 0)),
            text_length=int(d.get("text_length", 0)),
            template_family=str(d.get("template_family", "")),
            doc_type=str(d.get("doc_type", "other")),
            doc_type_confidence=str(d.get("doc_type_confidence", "low")),
            market_segment=str(d.get("market_segment", "uncertain")),
            segment_confidence=str(d.get("segment_confidence", "low")),
            cohort_included=bool(d.get("cohort_included", False)),
            word_count=int(d.get("word_count", 0)),
        )

    def get_doc(self, doc_id: str) -> DocRecord | None:
        """Get a document record by ID."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", [doc_id]
        ).fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in self._conn.description]
        d = dict(zip(cols, row, strict=True))
        return self._doc_from_row(d)

    def get_articles(self, doc_id: str) -> list[ArticleRecord]:
        """Get article-level records for a document.

        Returns empty list when the ``articles`` table is absent
        (backward compatibility with older corpus builds).
        """
        if "articles" not in self._table_names:
            return []
        rows = self._conn.execute(
            "SELECT doc_id, article_num, label, title, concept, "
            "char_start, char_end, is_synthetic "
            "FROM articles WHERE doc_id = ? ORDER BY article_num",
            [doc_id],
        ).fetchall()
        return [
            ArticleRecord(
                doc_id=str(r[0]),
                article_num=int(r[1]),
                label=str(r[2]),
                title=str(r[3]),
                concept=str(r[4]) if r[4] is not None else None,
                char_start=int(r[5]),
                char_end=int(r[6]),
                is_synthetic=bool(r[7]),
            )
            for r in rows
        ]

    def search_sections(
        self,
        *,
        heading_pattern: str | None = None,
        article_num: int | None = None,
        doc_id: str | None = None,
        cohort_only: bool = True,
        limit: int = 100,
    ) -> list[SectionRecord]:
        """Search sections by heading pattern, article number, or doc_id.

        Args:
            heading_pattern: SQL LIKE pattern for heading (e.g., '%Indebtedness%').
            article_num: Filter by article number.
            doc_id: Filter by document ID.
            cohort_only: If True, only search cohort-included documents.
            limit: Maximum number of results.

        Returns:
            List of SectionRecord sorted by doc_id, section_number.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if cohort_only:
            conditions.append(
                "s.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
            )

        if heading_pattern:
            conditions.append("s.heading ILIKE ?")
            params.append(heading_pattern)
        if article_num is not None:
            conditions.append("s.article_num = ?")
            params.append(article_num)
        if doc_id:
            conditions.append("s.doc_id = ?")
            params.append(doc_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"""
            SELECT s.doc_id, s.section_number, s.heading, s.char_start, s.char_end,
                   s.article_num, s.word_count
            FROM sections s
            WHERE {where}
            ORDER BY s.doc_id, s.char_start
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
        columns = {
            str(row[0])
            for row in self._conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'definitions'
                """
            ).fetchall()
        }

        select_parts = [
            "doc_id",
            "term",
            "definition_text",
            "char_start",
            "char_end",
            "pattern_engine",
            "confidence",
        ]
        for optional_col in (
            "definition_type",
            "definition_types",
            "type_confidence",
            "type_signals",
            "dependency_terms",
        ):
            if optional_col in columns:
                select_parts.append(optional_col)

        where_clause = "doc_id = ?"
        params: list[object] = [doc_id]
        if term:
            where_clause += " AND term ILIKE ?"
            params.append(term)

        query = (
            f"SELECT {', '.join(select_parts)} FROM definitions "
            f"WHERE {where_clause} ORDER BY char_start"
        )
        rows = self._conn.execute(query, params).fetchall()
        col_names = [str(desc[0]) for desc in self._conn.description]

        records: list[DefinitionRecord] = []
        for row in rows:
            payload = dict(zip(col_names, row, strict=True))
            records.append(
                DefinitionRecord(
                    doc_id=str(payload.get("doc_id", "")),
                    term=str(payload.get("term", "")),
                    definition_text=str(payload.get("definition_text", "")),
                    char_start=int(payload.get("char_start", 0) or 0),
                    char_end=int(payload.get("char_end", 0) or 0),
                    pattern_engine=str(payload.get("pattern_engine", "")),
                    confidence=float(payload.get("confidence", 0.0) or 0.0),
                    definition_type=str(payload.get("definition_type", "DIRECT") or "DIRECT"),
                    definition_types=_decode_string_tuple(payload.get("definition_types")),
                    type_confidence=float(payload.get("type_confidence", 0.0) or 0.0),
                    type_signals=_decode_string_tuple(payload.get("type_signals")),
                    dependency_terms=_decode_string_tuple(payload.get("dependency_terms")),
                )
            )
        return records

    def has_table(self, table_name: str) -> bool:
        """Whether the current DB contains a table."""
        return table_name in self._table_names

    def get_section_features(self, doc_id: str) -> dict[str, SectionFeatureRecord]:
        """Return section_features for a doc keyed by section_number.

        Returns empty dict when `section_features` is absent.
        """
        if not self.has_table("section_features"):
            return {}
        rows = self._conn.execute(
            """
            SELECT
                doc_id, section_number, article_num, char_start, char_end,
                word_count, char_count, heading_lower, scope_label,
                scope_operator_count, scope_permit_count, scope_restrict_count,
                scope_estimated_depth, preemption_override_count,
                preemption_yield_count, preemption_estimated_depth,
                preemption_has, preemption_edge_count, definition_types,
                definition_type_primary, definition_type_confidence
            FROM section_features
            WHERE doc_id = ?
            """,
            [doc_id],
        ).fetchall()
        out: dict[str, SectionFeatureRecord] = {}
        for row in rows:
            record = SectionFeatureRecord(
                doc_id=str(row[0]),
                section_number=str(row[1]),
                article_num=int(row[2] or 0),
                char_start=int(row[3] or 0),
                char_end=int(row[4] or 0),
                word_count=int(row[5] or 0),
                char_count=int(row[6] or 0),
                heading_lower=str(row[7] or ""),
                scope_label=str(row[8] or ""),
                scope_operator_count=int(row[9] or 0),
                scope_permit_count=int(row[10] or 0),
                scope_restrict_count=int(row[11] or 0),
                scope_estimated_depth=int(row[12] or 0),
                preemption_override_count=int(row[13] or 0),
                preemption_yield_count=int(row[14] or 0),
                preemption_estimated_depth=int(row[15] or 0),
                preemption_has=bool(row[16]),
                preemption_edge_count=int(row[17] or 0),
                definition_types=_decode_string_tuple(row[18]),
                definition_type_primary=str(row[19] or ""),
                definition_type_confidence=float(row[20] or 0.0),
            )
            out[record.section_number] = record
        return out

    def get_clause_features(
        self,
        doc_id: str,
        section_number: str,
    ) -> list[ClauseFeatureRecord]:
        """Return clause features for a section.

        Returns empty list when `clause_features` is absent.
        """
        if not self.has_table("clause_features"):
            return []
        rows = self._conn.execute(
            """
            SELECT
                doc_id, section_number, clause_id, depth, level_type,
                token_count, char_count, has_digits, parse_confidence, is_structural
            FROM clause_features
            WHERE doc_id = ? AND section_number = ?
            ORDER BY clause_id
            """,
            [doc_id, section_number],
        ).fetchall()
        return [
            ClauseFeatureRecord(
                doc_id=str(r[0]),
                section_number=str(r[1]),
                clause_id=str(r[2]),
                depth=int(r[3] or 0),
                level_type=str(r[4] or ""),
                token_count=int(r[5] or 0),
                char_count=int(r[6] or 0),
                has_digits=bool(r[7]),
                parse_confidence=float(r[8] or 0.0),
                is_structural=bool(r[9]),
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
        cohort_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Full-text search across section text.

        Args:
            pattern: Search pattern (SQL LIKE with % wildcards).
            context_chars: Number of context characters to return.
            max_results: Maximum number of results.
            doc_ids: Optional list of doc_ids to restrict search to.
            cohort_only: If True, only search cohort-included documents.

        Returns:
            List of dicts with doc_id, section_number, matched text, context.
        """
        conditions = ["st.text ILIKE ?"]
        params: list[Any] = [f"%{pattern}%"]

        if cohort_only:
            conditions.append(
                "st.doc_id IN (SELECT doc_id FROM documents WHERE cohort_included = true)"
            )

        if doc_ids:
            placeholders = ",".join(["?"] * len(doc_ids))
            conditions.append(f"st.doc_id IN ({placeholders})")
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
        cohort_only: bool = True,
    ) -> list[str]:
        """Select a random sample of document IDs.

        Args:
            n: Number of documents to sample.
            seed: Random seed for reproducibility.
            stratify_by: Column to stratify by (e.g., 'template_family').
            cohort_only: If True, only sample from cohort-included documents.

        Returns:
            List of doc_id strings.
        """
        cohort_filter = " WHERE cohort_included = true" if cohort_only else ""
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
                    FROM documents{cohort_filter}
                ) sub
                WHERE rn <= GREATEST(1, CAST(? * group_size / total_size AS INTEGER))
                LIMIT ?
            """
            rows = self._conn.execute(query, [seed, n, n]).fetchall()
        else:
            query = f"""
                SELECT doc_id FROM documents{cohort_filter}
                ORDER BY hash(doc_id || ?) % 1000000
                LIMIT ?
            """
            rows = self._conn.execute(query, [seed, n]).fetchall()

        return [str(r[0]) for r in rows]
