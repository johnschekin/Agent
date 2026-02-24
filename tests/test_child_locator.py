"""Tests for child_locator clause text derivation."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb


def _load_child_locator_module() -> object:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "child_locator.py"
    spec = importlib.util.spec_from_file_location("child_locator", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestChildLocator:
    def test_derives_clause_text_from_global_spans(self) -> None:
        mod = _load_child_locator_module()
        section_text = "alpha leverage ratio covenant"
        got = mod._derive_clause_text(
            section_text,
            span_start=106,
            span_end=120,
            section_char_start=100,
        )
        assert got == "leverage ratio"

    def test_falls_back_to_section_relative_spans(self) -> None:
        mod = _load_child_locator_module()
        section_text = "alpha leverage ratio covenant"
        got = mod._derive_clause_text(
            section_text,
            span_start=6,
            span_end=20,
            section_char_start=100,
        )
        assert got == "leverage ratio"

    def test_returns_empty_for_invalid_spans(self) -> None:
        mod = _load_child_locator_module()
        section_text = "alpha leverage ratio covenant"
        got = mod._derive_clause_text(
            section_text,
            span_start=200,
            span_end=220,
            section_char_start=100,
        )
        assert got == ""

    def test_emit_not_found_for_parent_without_matches(self, tmp_path: Path) -> None:
        root = Path(__file__).resolve().parents[1]
        db_path = tmp_path / "corpus.duckdb"
        parent_path = tmp_path / "parents.json"

        con = duckdb.connect(str(db_path))
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
                doc_id VARCHAR,
                template_family VARCHAR,
                cohort_included BOOLEAN
            )
            """
        )
        con.execute(
            """
            CREATE TABLE clauses (
                doc_id VARCHAR,
                section_number VARCHAR,
                clause_id VARCHAR,
                depth INTEGER,
                header_text VARCHAR,
                clause_text VARCHAR,
                span_start INTEGER,
                span_end INTEGER
            )
            """
        )
        con.execute("INSERT INTO documents VALUES ('d1', 'cluster_001', true)")
        con.execute(
            """
            INSERT INTO clauses VALUES
            ('d1', '7.01', 'a', 1, 'Debt Basket', 'Permitted debt text', 0, 20)
            """
        )
        con.close()

        parent_path.write_text(
            json.dumps([{"doc_id": "d1", "section_number": "7.01"}])
        )

        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        proc = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "child_locator.py"),
                "--db",
                str(db_path),
                "--parent-matches",
                str(parent_path),
                "--child-keywords",
                "nonexistent-keyword",
                "--emit-not-found",
                "--run-id",
                "child_run_1",
                "--ontology-node-id",
                "debt_capacity.indebtedness.ratio_debt",
            ],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        rows = json.loads(proc.stdout)
        assert isinstance(rows, list)
        assert len(rows) == 1
        assert rows[0]["record_type"] == "NOT_FOUND"
        assert rows[0]["run_id"] == "child_run_1"
        assert rows[0]["ontology_node_id"] == "debt_capacity.indebtedness.ratio_debt"
        assert rows[0]["template_family"] == "cluster_001"
