from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb


def _make_test_db(path: Path) -> None:
    conn = duckdb.connect(str(path))
    conn.execute(
        """
        CREATE TABLE clauses (
            doc_id VARCHAR,
            section_number VARCHAR,
            clause_id VARCHAR,
            label VARCHAR,
            depth INTEGER,
            clause_text VARCHAR,
            is_structural BOOLEAN
        )
        """,
    )
    conn.close()


def _run_guardrail(db_path: Path, baseline_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/edge_case_clause_parent_guardrail.py",
            "--db",
            str(db_path),
            "--baseline",
            str(baseline_path),
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )


def test_parent_guardrail_passes_when_within_baseline(tmp_path: Path) -> None:
    db_path = tmp_path / "pass_parent.duckdb"
    _make_test_db(db_path)

    baseline_path = tmp_path / "parent_baseline.json"
    write_proc = subprocess.run(
        [
            sys.executable,
            "scripts/edge_case_clause_parent_guardrail.py",
            "--db",
            str(db_path),
            "--baseline",
            str(baseline_path),
            "--write-baseline",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert write_proc.returncode == 0, write_proc.stderr

    proc = _run_guardrail(db_path, baseline_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "pass"
    assert payload["failures"] == []


def test_parent_guardrail_fails_on_xy_parent_loss_regression(tmp_path: Path) -> None:
    db_path = tmp_path / "fail_parent.duckdb"
    _make_test_db(db_path)

    baseline_path = tmp_path / "parent_baseline.json"
    write_proc = subprocess.run(
        [
            sys.executable,
            "scripts/edge_case_clause_parent_guardrail.py",
            "--db",
            str(db_path),
            "--baseline",
            str(baseline_path),
            "--write-baseline",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert write_proc.returncode == 0, write_proc.stderr

    conn = duckdb.connect(str(db_path))
    # Simulate a suspicious section:
    # - root (a) includes inline (y)
    # - parser also emits a root y clause in same section
    conn.execute(
        "INSERT INTO clauses VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "doc-regress",
            "2.21",
            "a",
            "(a)",
            1,
            "(a) Borrower may request commitments, and (y) lenders may decline.",
            True,
        ],
    )
    conn.execute(
        "INSERT INTO clauses VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "doc-regress",
            "2.21",
            "y",
            "(y)",
            1,
            "(y) lenders may decline.",
            True,
        ],
    )
    conn.close()

    proc = _run_guardrail(db_path, baseline_path)
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    failed_metrics = {item["metric"] for item in payload["failures"]}
    assert "xy_parent_loss.docs" in failed_metrics
