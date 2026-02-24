"""Smoke test for benchmark_pipeline CLI."""
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
    con.execute("CREATE TABLE clauses (doc_id VARCHAR)")
    con.execute("CREATE TABLE definitions (doc_id VARCHAR)")
    con.execute(
        """
        INSERT INTO documents VALUES ('doc1', 'cluster_001', true)
        """
    )
    con.execute(
        """
        INSERT INTO sections VALUES
        ('doc1', '7.01', 'Limitation on Indebtedness', 0, 100, 7, 20)
        """
    )
    con.execute(
        """
        INSERT INTO section_text VALUES
        ('doc1', '7.01', 'The Borrower shall not incur Indebtedness except as permitted.')
        """
    )
    con.close()


def test_benchmark_pipeline_pattern_tester_smoke(tmp_path: Path) -> None:
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
            }
        )
    )

    output_json = tmp_path / "benchmark.json"
    output_md = tmp_path / "benchmark.md"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "benchmark_pipeline.py"),
            "--db",
            str(db_path),
            "--strategy",
            str(strategy_path),
            "--tools",
            "pattern_tester",
            "--sample-sizes",
            "1",
            "--include-all",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert output_json.exists()
    assert output_md.exists()

    report = json.loads(output_json.read_text())
    assert report["schema_version"] == "benchmark_pipeline_v1"
    assert len(report["results"]) == 1
    result = report["results"][0]
    assert result["tool"] == "pattern_tester"
    assert int(result["evaluated_docs"]) >= 1
