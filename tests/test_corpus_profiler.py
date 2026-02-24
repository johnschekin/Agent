"""Smoke test for corpus_profiler CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
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
            doc_type VARCHAR,
            market_segment VARCHAR,
            template_family VARCHAR,
            cohort_included BOOLEAN,
            word_count INTEGER,
            section_count INTEGER,
            clause_count INTEGER,
            definition_count INTEGER,
            facility_size_mm DOUBLE
        )
        """
    )
    con.execute(
        """
        INSERT INTO documents VALUES
        ('d1', 'credit_agreement', 'leveraged', 'cluster_001', true, 5000, 20, 80, 120, 1200.0),
        ('d2', 'amendment', 'uncertain', '', false, 1500, 5, 0, 10, NULL)
        """
    )
    con.close()


def _write_manifest(path: Path, *, run_id: str, docs: int) -> None:
    payload = {
        "manifest_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "schema_version": "0.2.0",
        "table_row_counts": {
            "documents": docs,
            "sections": docs,
            "clauses": docs,
            "definitions": docs,
            "section_text": docs,
        },
        "errors_count": 0,
    }
    path.write_text(json.dumps(payload))


def test_corpus_profiler_outputs_profile(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "corpus.duckdb"
    out_path = tmp_path / "corpus_profile.json"
    _build_db(db_path)
    _write_manifest(tmp_path / "run_manifest.json", run_id="current_run", docs=2)
    compare_manifest = tmp_path / "previous_manifest.json"
    _write_manifest(compare_manifest, run_id="previous_run", docs=1)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "corpus_profiler.py"),
            "--db",
            str(db_path),
            "--output",
            str(out_path),
            "--include-all",
            "--compare-manifest",
            str(compare_manifest),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert out_path.exists()

    profile = json.loads(out_path.read_text())
    assert profile["counts"]["total_docs"] == 2
    assert "distributions" in profile
    assert profile["manifest"]["present"] is True
    assert profile["manifest"]["run_id"] == "current_run"
    assert profile["manifest_comparison"]["table_row_count_delta"]["documents"] == 1
    assert "zero_clauses_details" in profile["anomalies"]
    assert profile["anomalies"]["zero_clauses_details"][0]["doc_id"] == "d2"
    assert "template_family" in profile["anomalies"]["zero_clauses_details"][0]
    assert "failure_signatures" in profile["anomalies"]["zero_clauses_details"][0]
