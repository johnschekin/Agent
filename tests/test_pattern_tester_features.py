"""Tests for pattern_tester materialized feature table integration."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb


def _build_db(path: Path) -> None:
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
        "INSERT INTO _schema_version VALUES ('corpus', '0.2.0', current_timestamp)"
    )
    con.execute(
        """
        CREATE TABLE documents (
            doc_id VARCHAR PRIMARY KEY,
            template_family VARCHAR,
            cohort_included BOOLEAN
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
        CREATE TABLE section_text (
            doc_id VARCHAR,
            section_number VARCHAR,
            text VARCHAR
        )
        """
    )
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
    con.execute("INSERT INTO documents VALUES ('doc1', 'cluster_001', true)")
    con.execute(
        """
        INSERT INTO sections VALUES
        ('doc1', '7.01', 'Limitation on Indebtedness', 0, 100, 7, 30)
        """
    )
    con.execute(
        """
        INSERT INTO section_text VALUES
        ('doc1', '7.01', 'The Borrower shall not incur Indebtedness except as permitted.')
        """
    )
    con.execute(
        """
        INSERT INTO section_features VALUES
        (
            'doc1', '7.01', 7, 0, 100, 30, 100, 'limitation on indebtedness',
            'NARROW', 4, 1, 3, 2, 1, 1, 2, true, 2,
            '["FORMULAIC"]', 'FORMULAIC', 0.8
        )
        """
    )
    con.close()


def test_pattern_tester_reports_feature_table_usage(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "corpus.duckdb"
    _build_db(db_path)

    strategy_path = tmp_path / "strategy.json"
    strategy_path.write_text(
        json.dumps(
            {
                "concept_id": "debt_capacity.indebtedness",
                "concept_name": "Indebtedness",
                "family": "indebtedness",
                "heading_patterns": ["Limitation on Indebtedness"],
                "keyword_anchors": ["indebtedness"],
            },
            indent=2,
        )
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "pattern_tester.py"),
            "--db",
            str(db_path),
            "--strategy",
            str(strategy_path),
            "--sample",
            "1",
            "--include-all",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["feature_tables"]["section_features_present"] is True
    assert payload["feature_tables"]["docs_with_section_features"] == 1
