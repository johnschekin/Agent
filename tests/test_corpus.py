"""Tests for agent.corpus module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import duckdb

from agent.corpus import (
    SCHEMA_VERSION,
    CorpusIndex,
    SchemaVersionError,
    ensure_schema_version,
    load_candidate_doc_ids,
)


def _create_min_corpus_db(path: Path, *, schema_version: str = SCHEMA_VERSION) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        """
        CREATE TABLE _schema_version (
            table_name VARCHAR PRIMARY KEY,
            version VARCHAR NOT NULL,
            created_at TIMESTAMP
        )
        """
    )
    con.execute(
        "INSERT INTO _schema_version VALUES ('corpus', ?, current_timestamp)",
        [schema_version],
    )
    con.execute(
        """
        CREATE TABLE documents (
            doc_id VARCHAR PRIMARY KEY,
            cik VARCHAR,
            accession VARCHAR,
            path VARCHAR,
            borrower VARCHAR,
            admin_agent VARCHAR,
            facility_size_mm DOUBLE,
            closing_date DATE,
            filing_date DATE,
            form_type VARCHAR,
            template_family VARCHAR,
            section_count INTEGER,
            clause_count INTEGER,
            definition_count INTEGER,
            text_length INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE sections (
            doc_id VARCHAR,
            section_number VARCHAR,
            heading VARCHAR,
            char_start INTEGER,
            char_end INTEGER,
            article_num INTEGER,
            word_count INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE clauses (
            doc_id VARCHAR,
            section_number VARCHAR,
            clause_id VARCHAR,
            label VARCHAR,
            depth INTEGER,
            level_type VARCHAR,
            span_start INTEGER,
            span_end INTEGER,
            header_text VARCHAR,
            parent_id VARCHAR,
            is_structural BOOLEAN,
            parse_confidence DOUBLE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE definitions (
            doc_id VARCHAR,
            term VARCHAR,
            definition_text VARCHAR,
            char_start INTEGER,
            char_end INTEGER,
            pattern_engine VARCHAR,
            confidence DOUBLE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE section_text (
            doc_id VARCHAR,
            section_number VARCHAR,
            text VARCHAR
        )
        """
    )
    con.execute(
        """
        INSERT INTO documents VALUES
        ('doc1', '0001', 'acc1', 'documents/doc1.htm', 'Borrower LLC', 'JPMorgan',
         500.0, NULL, NULL, 'EX-10.1', 'kirkland', 1, 1, 1, 120)
        """
    )
    con.execute(
        "INSERT INTO sections VALUES ('doc1', '7.01', 'Indebtedness', 0, 120, 7, 20)"
    )
    con.execute(
        """
        INSERT INTO clauses VALUES
        ('doc1', '7.01', 'c1', '(a)', 1, 'alpha', 0, 60, 'Debt Basket', '', true, 0.9)
        """
    )
    con.execute(
        """
        INSERT INTO definitions VALUES
        ('doc1', 'Indebtedness', 'means debt obligations', 0, 24, 'quoted', 0.92)
        """
    )
    con.execute(
        """
        INSERT INTO section_text VALUES
        ('doc1', '7.01', 'Limitation on Indebtedness and Permitted Debt')
        """
    )
    con.close()


class TestCorpusIndex:
    def test_reads_doc_and_section_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "corpus.duckdb"
            _create_min_corpus_db(db_path)
            with CorpusIndex(db_path) as corpus:
                assert corpus.schema_version == SCHEMA_VERSION
                assert corpus.doc_count == 1
                doc = corpus.get_doc("doc1")
                assert doc is not None
                assert doc.borrower == "Borrower LLC"
                assert corpus.get_section_text("doc1", "7.01") is not None

    def test_schema_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "corpus.duckdb"
            _create_min_corpus_db(db_path, schema_version="0.0.0")
            try:
                CorpusIndex(db_path)
                raise AssertionError("Expected SchemaVersionError")
            except SchemaVersionError:
                pass

    def test_schema_mismatch_can_be_bypassed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "corpus.duckdb"
            _create_min_corpus_db(db_path, schema_version="0.0.0")
            with CorpusIndex(db_path, enforce_schema=False) as corpus:
                assert corpus.doc_count == 1

    def test_ensure_schema_version_on_raw_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "corpus.duckdb"
            _create_min_corpus_db(db_path)
            con = duckdb.connect(str(db_path), read_only=True)
            actual = ensure_schema_version(con, db_path=db_path)
            assert actual == SCHEMA_VERSION
            con.close()

    def test_run_manifest_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "corpus.duckdb"
            _create_min_corpus_db(db_path)
            manifest_path = db_path.parent / "run_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "manifest_version": "1.0",
                        "run_id": "test_run",
                        "table_row_counts": {"documents": 1},
                    }
                )
            )
            with CorpusIndex(db_path) as corpus:
                assert corpus.run_manifest_path == manifest_path
                manifest = corpus.get_run_manifest()
                assert manifest is not None
                assert manifest["run_id"] == "test_run"

    def test_section_feature_table_absent_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "corpus.duckdb"
            _create_min_corpus_db(db_path)
            with CorpusIndex(db_path) as corpus:
                assert corpus.has_table("section_features") is False
                assert corpus.get_section_features("doc1") == {}

    def test_section_feature_table_reads_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "corpus.duckdb"
            _create_min_corpus_db(db_path)
            con = duckdb.connect(str(db_path))
            con.execute(
                """
                CREATE TABLE section_features (
                    doc_id VARCHAR,
                    section_number VARCHAR,
                    article_num INTEGER,
                    char_start INTEGER,
                    char_end INTEGER,
                    word_count INTEGER,
                    char_count INTEGER,
                    heading_lower VARCHAR,
                    scope_label VARCHAR,
                    scope_operator_count INTEGER,
                    scope_permit_count INTEGER,
                    scope_restrict_count INTEGER,
                    scope_estimated_depth INTEGER,
                    preemption_override_count INTEGER,
                    preemption_yield_count INTEGER,
                    preemption_estimated_depth INTEGER,
                    preemption_has BOOLEAN,
                    preemption_edge_count INTEGER,
                    definition_types VARCHAR,
                    definition_type_primary VARCHAR,
                    definition_type_confidence DOUBLE
                )
                """
            )
            con.execute(
                """
                INSERT INTO section_features VALUES
                (
                    'doc1', '7.01', 7, 0, 120, 20, 120, 'indebtedness',
                    'NARROW', 4, 1, 3, 2, 1, 1, 2, true, 2,
                    '["FORMULAIC"]', 'FORMULAIC', 0.8
                )
                """
            )
            con.close()
            with CorpusIndex(db_path) as corpus:
                assert corpus.has_table("section_features") is True
                feats = corpus.get_section_features("doc1")
                assert "7.01" in feats
                assert feats["7.01"].scope_label == "NARROW"
                assert feats["7.01"].definition_types == ("FORMULAIC",)

    def test_load_candidate_doc_ids_from_text_and_dedup(self, tmp_path: Path) -> None:
        txt_path = tmp_path / "candidates.txt"
        txt_path.write_text("doc1\ndoc2\ndoc1\n\n")
        assert load_candidate_doc_ids(txt_path) == ["doc1", "doc2"]

    def test_load_candidate_doc_ids_from_json_payload(self, tmp_path: Path) -> None:
        json_path = tmp_path / "candidates.json"
        json_path.write_text(
            json.dumps(
                {
                    "candidates": [
                        {"doc_id": "docA"},
                        "docB",
                        {"doc_id": "docA"},
                    ]
                }
            )
        )
        assert load_candidate_doc_ids(json_path) == ["docA", "docB"]
