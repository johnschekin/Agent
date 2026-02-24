"""Smoke test for template_classifier CLI."""
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
            cohort_included BOOLEAN,
            template_family VARCHAR DEFAULT ''
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
        ('d1', true, ''),
        ('d2', true, ''),
        ('d3', true, '')
        """
    )
    con.execute(
        """
        INSERT INTO section_text VALUES
        ('d1', '1.01', 'Definitions. "Indebtedness" means debt obligations.'),
        ('d1', '7.01', 'Limitation on Indebtedness.'),
        ('d2', '1.01', 'Definitions. "Indebtedness" means debt obligations.'),
        ('d2', '7.01', 'Limitation on Indebtedness.'),
        ('d3', '1.01', 'Definitions. "Restricted Payment" means any dividend.'),
        ('d3', '7.06', 'Limitation on Restricted Payments.')
        """
    )
    con.close()


def test_template_classifier_writes_output(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "corpus.duckdb"
    out_path = tmp_path / "classifications.json"
    _build_db(db_path)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "template_classifier.py"),
            "--db",
            str(db_path),
            "--output",
            str(out_path),
            "--no-write-db",
            "--min-samples",
            "1",
            "--eps",
            "0.5",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["status"] in {"ok", "quality_gates_failed"}
    assert out_path.exists()

    out = json.loads(out_path.read_text())
    assert set(out.keys()) == {"d1", "d2", "d3"}
    assert "quality_metrics" in payload
    assert "quality_gates" in payload
    assert "assignment_signature" in payload
    assert payload["report_path"]
    report = json.loads(Path(payload["report_path"]).read_text())
    assert report["schema_version"] == "template_classifier_report_v1"
    assert report["documents"] == 3
    assert "cluster_diagnostics" in report


def test_template_classifier_fail_on_gate_exits_nonzero(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "corpus.duckdb"
    out_path = tmp_path / "classifications.json"
    _build_db(db_path)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "template_classifier.py"),
            "--db",
            str(db_path),
            "--output",
            str(out_path),
            "--no-write-db",
            "--min-samples",
            "1",
            "--eps",
            "0.5",
            "--min-clusters",
            "10",
            "--fail-on-gate",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["status"] == "quality_gates_failed"
    assert payload["quality_gates"]["passed"] is False
