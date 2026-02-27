from __future__ import annotations

import json
import string
import subprocess
import sys
from pathlib import Path

import duckdb


def _make_test_db(path: Path) -> None:
    conn = duckdb.connect(str(path))
    conn.execute(
        """
        CREATE TABLE sections (
            doc_id VARCHAR,
            section_number VARCHAR,
            char_start INTEGER
        )
        """,
    )
    conn.execute(
        """
        CREATE TABLE section_text (
            doc_id VARCHAR,
            section_number VARCHAR,
            text VARCHAR
        )
        """,
    )
    conn.execute(
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
            clause_text VARCHAR,
            parent_id VARCHAR,
            is_structural BOOLEAN,
            parse_confidence DOUBLE
        )
        """,
    )
    conn.close()


def _run_shadow_diff(
    db_path: Path,
    *,
    mode: str,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "scripts/clause_shadow_reparse_diff.py",
        "--db",
        str(db_path),
        "--mode",
        mode,
        "--json",
        "--limit-sections",
        "50",
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def test_shadow_diff_detects_parent_loss_repair_without_rebuild(tmp_path: Path) -> None:
    db_path = tmp_path / "shadow_parent_fix.duckdb"
    _make_test_db(db_path)
    conn = duckdb.connect(str(db_path))

    section_text = (
        "(a) General. Borrower may request incremental facilities, provided that "
        "(i) requirements are met and (ii) documentation is delivered; "
        "(I) no default exists; (II) pricing is agreed; and (b) below applies; "
        "(x) no default shall exist and (y) each lender executes a joinder agreement.\n"
        "(b) Procedures. Additional steps apply.\n"
        "(c) Funding. On the effective date, funding occurs.\n"
    )
    conn.execute(
        "INSERT INTO sections VALUES (?, ?, ?)",
        ["doc-1", "2.14", 0],
    )
    conn.execute(
        "INSERT INTO section_text VALUES (?, ?, ?)",
        ["doc-1", "2.14", section_text],
    )

    # Persisted rows simulate pre-fix parent-loss parse:
    # (x)/(y) wrongly emitted as root clauses.
    persisted_rows = [
        (
            "doc-1",
            "2.14",
            "a",
            "(a)",
            1,
            "alpha",
            0,
            300,
            "(a) ... and (x) no default and (y) joinder ...",
            "",
            True,
            0.8,
        ),
        ("doc-1", "2.14", "x", "(x)", 1, "alpha", 301, 340, "(x) no default ...", "", True, 0.7),
        ("doc-1", "2.14", "y", "(y)", 1, "alpha", 341, 380, "(y) joinder ...", "", True, 0.7),
        ("doc-1", "2.14", "b", "(b)", 1, "alpha", 381, 450, "(b) Procedures ...", "", True, 0.8),
    ]
    conn.executemany(
        "INSERT INTO clauses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        persisted_rows,
    )
    conn.close()

    proc = _run_shadow_diff(db_path, mode="parent-loss")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "pass"
    assert payload["sections_selected"] == 1

    persisted_sections = payload["summary"]["persisted_metrics"]["xy_parent_loss"]["sections"]
    shadow_sections = payload["summary"]["shadow_metrics"]["xy_parent_loss"]["sections"]
    fixed_sections = payload["summary"]["section_signals"]["fixed_root_xy_sections"]
    assert persisted_sections >= 1
    assert shadow_sections <= persisted_sections
    assert fixed_sections >= 1


def test_shadow_diff_can_fail_on_new_root_xy_regression(tmp_path: Path) -> None:
    db_path = tmp_path / "shadow_regression.duckdb"
    _make_test_db(db_path)
    conn = duckdb.connect(str(db_path))

    # Sequential root alpha lines through (y) should stay root in shadow parse.
    lines = [f"({ch}) root clause {ch}." for ch in string.ascii_lowercase[:25]]  # a..y
    section_text = "\n".join(lines) + "\n"
    conn.execute(
        "INSERT INTO sections VALUES (?, ?, ?)",
        ["doc-2", "3.01", 0],
    )
    conn.execute(
        "INSERT INTO section_text VALUES (?, ?, ?)",
        ["doc-2", "3.01", section_text],
    )

    # Persisted rows intentionally omit (x)/(y), so shadow should be flagged
    # as regression when fail mode is enabled.
    conn.executemany(
        "INSERT INTO clauses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("doc-2", "3.01", "a", "(a)", 1, "alpha", 0, 20, "(a) root clause a.", "", True, 0.9),
            ("doc-2", "3.01", "b", "(b)", 1, "alpha", 21, 40, "(b) root clause b.", "", True, 0.9),
        ],
    )
    conn.close()

    proc = _run_shadow_diff(
        db_path,
        mode="all",
        extra_args=["--fail-on-regression", "--max-structural-delta-ratio", "20.0"],
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    failed_metrics = {item["metric"] for item in payload["failures"]}
    assert (
        "sections_with_root_xy" in failed_metrics
        or "regressed_root_xy_sections" in failed_metrics
    )
