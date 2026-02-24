"""Tests for coverage_reporter candidate-set filtering and outputs."""
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
        INSERT INTO documents VALUES
        ('doc_hit', 'cluster_a', true),
        ('doc_miss', 'cluster_b', true)
        """
    )
    con.execute(
        """
        INSERT INTO sections VALUES
        ('doc_hit', '7.01', 'Limitation on Indebtedness', 0, 100, 7, 30),
        ('doc_miss', '7.02', 'Investments', 101, 220, 7, 35)
        """
    )
    con.execute(
        """
        INSERT INTO section_text VALUES
        ('doc_hit', '7.01', 'The Borrower shall not incur Indebtedness except as permitted.'),
        ('doc_miss', '7.02', 'The Borrower shall not make Investments except as permitted.')
        """
    )
    con.close()


def _run_coverage(root: Path, args: list[str]) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "coverage_reporter.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_coverage_reporter_candidate_subset_and_output(tmp_path: Path) -> None:
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

    doc_ids_path = tmp_path / "doc_ids.txt"
    doc_ids_path.write_text("doc_hit\ndoc_miss\n")
    candidates_in = tmp_path / "family_candidates_in.json"
    candidates_in.write_text(json.dumps({"doc_ids": ["doc_hit"]}))
    candidates_out = tmp_path / "family_candidates_out.json"

    output = _run_coverage(
        root,
        [
            "--db",
            str(db_path),
            "--strategy",
            str(strategy_path),
            "--doc-ids",
            str(doc_ids_path),
            "--family-candidates-in",
            str(candidates_in),
            "--family-candidates-out",
            str(candidates_out),
            "--include-all",
        ],
    )

    assert output["schema_version"] == "coverage_reporter_v2"
    assert output["ontology_node_id"] == "debt_capacity.indebtedness"
    assert output["strategy_version"] == 1
    candidate_set = output["candidate_set"]
    assert candidate_set["input_doc_count"] == 2
    assert candidate_set["candidate_input_count"] == 1
    assert candidate_set["evaluated_doc_count"] == 1
    assert candidate_set["pruning_ratio"] == 0.5
    assert output["overall"]["n"] == 1
    assert output["overall"]["hits"] == 1
    assert output["overall"]["hit_rate"] == 1.0

    payload = json.loads(candidates_out.read_text())
    assert payload["schema_version"] == "family_candidates_v1"
    assert payload["doc_ids"] == ["doc_hit"]
    assert payload["hit_count"] == 1


def test_coverage_reporter_cluster_grouping_uses_classifications(tmp_path: Path) -> None:
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

    classifications_path = tmp_path / "classifications.json"
    classifications_path.write_text(
        json.dumps(
            {
                "doc_hit": {"cluster_id": 7, "template_family": "cluster_007"},
                "doc_miss": {"cluster_id": -1, "template_family": "noise"},
            }
        )
    )

    output = _run_coverage(
        root,
        [
            "--db",
            str(db_path),
            "--strategy",
            str(strategy_path),
            "--group-by",
            "cluster_id",
            "--template-classifications",
            str(classifications_path),
            "--include-all",
        ],
    )

    assert output["grouping"]["template_classifications_loaded"] == 2
    assert output["grouping"]["group_by"] == "cluster_id"
    by_group = output["by_group"]
    assert set(by_group.keys()) == {"7", "noise"}
    assert by_group["7"]["hits"] == 1
