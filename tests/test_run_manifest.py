"""Tests for agent.run_manifest utilities."""
from __future__ import annotations

from pathlib import Path

import duckdb

from agent.run_manifest import (
    build_manifest,
    compare_manifests,
    generate_run_id,
    load_manifest,
    write_manifest,
)


def _create_db(path: Path, *, docs: int) -> None:
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
    con.execute("CREATE TABLE documents (doc_id VARCHAR)")
    con.execute("CREATE TABLE sections (doc_id VARCHAR, section_number VARCHAR)")
    con.execute(
        "CREATE TABLE clauses (doc_id VARCHAR, section_number VARCHAR, clause_id VARCHAR)"
    )
    con.execute("CREATE TABLE definitions (doc_id VARCHAR, term VARCHAR)")
    con.execute("CREATE TABLE section_text (doc_id VARCHAR, section_number VARCHAR)")
    for i in range(docs):
        did = f"d{i + 1}"
        con.execute("INSERT INTO documents VALUES (?)", [did])
        con.execute("INSERT INTO sections VALUES (?, '7.01')", [did])
        con.execute("INSERT INTO clauses VALUES (?, '7.01', 'a')", [did])
        con.execute("INSERT INTO definitions VALUES (?, 'Indebtedness')", [did])
        con.execute("INSERT INTO section_text VALUES (?, '7.01')", [did])
    con.close()


def test_write_and_load_manifest(tmp_path: Path) -> None:
    db_path = tmp_path / "corpus.duckdb"
    _create_db(db_path, docs=2)

    run_id = generate_run_id("test_run")
    manifest = build_manifest(
        run_id=run_id,
        db_path=db_path,
        input_source={"mode": "test"},
        timings_sec={"total": 1.25},
        errors_count=1,
        stats={"processed_docs": 2},
        git_commit="deadbeef",
    )
    canonical_path, versioned_path = write_manifest(db_path, manifest)
    assert canonical_path.exists()
    assert versioned_path.exists()

    loaded = load_manifest(canonical_path)
    assert loaded["run_id"] == run_id
    assert loaded["table_row_counts"]["documents"] == 2
    assert loaded["errors_count"] == 1


def test_compare_manifests_row_deltas(tmp_path: Path) -> None:
    db1 = tmp_path / "corpus_a.duckdb"
    db2 = tmp_path / "corpus_b.duckdb"
    _create_db(db1, docs=1)
    _create_db(db2, docs=3)

    older = build_manifest(
        run_id="old",
        db_path=db1,
        input_source={"mode": "test"},
        timings_sec={"total": 1.0},
        errors_count=2,
    )
    newer = build_manifest(
        run_id="new",
        db_path=db2,
        input_source={"mode": "test"},
        timings_sec={"total": 1.1},
        errors_count=1,
    )

    delta = compare_manifests(newer, older)
    assert delta["schema_version_changed"] is False
    assert delta["table_row_count_delta"]["documents"] == 2
    assert delta["errors_count_delta"] == -1
