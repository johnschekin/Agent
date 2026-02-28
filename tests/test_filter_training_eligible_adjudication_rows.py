from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "filter_training_eligible_adjudication_rows.py"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_filter_training_eligible_rows(tmp_path: Path) -> None:
    input_path = tmp_path / "batch.jsonl"
    _write_jsonl(
        input_path,
        [
            {"row_id": "ROW-1", "decision": "accepted"},
            {
                "row_id": "ROW-2",
                "decision": "abstain",
                "training_export_eligible": False,
            },
            {
                "row_id": "ROW-3",
                "decision": "review",
                "quality_flags": ["toc_or_index_noise"],
            },
        ],
    )
    out_path = tmp_path / "eligible.jsonl"
    quarantine_path = tmp_path / "quarantine.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--out",
            str(out_path),
            "--quarantine-out",
            str(quarantine_path),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    eligible_rows = [
        json.loads(line)
        for line in out_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["row_id"] for row in eligible_rows] == ["ROW-1"]

    quarantine = json.loads(quarantine_path.read_text(encoding="utf-8"))
    assert quarantine["quarantined_rows"] == 2
    assert {item["row_id"] for item in quarantine["quarantine"]} == {"ROW-2", "ROW-3"}


def test_filter_training_eligible_allows_uncertain_override(tmp_path: Path) -> None:
    input_path = tmp_path / "batch.jsonl"
    _write_jsonl(
        input_path,
        [
            {
                "row_id": "ROW-1",
                "decision": "review",
                "allow_uncertain_training_export": True,
            },
            {"row_id": "ROW-2", "decision": "accepted"},
        ],
    )
    out_path = tmp_path / "eligible.jsonl"
    quarantine_path = tmp_path / "quarantine.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--out",
            str(out_path),
            "--quarantine-out",
            str(quarantine_path),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    eligible_rows = [
        json.loads(line)
        for line in out_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["row_id"] for row in eligible_rows} == {"ROW-1", "ROW-2"}
    quarantine = json.loads(quarantine_path.read_text(encoding="utf-8"))
    assert quarantine["quarantined_rows"] == 0


def test_filter_training_eligible_rows_missing_input(tmp_path: Path) -> None:
    out_path = tmp_path / "eligible.jsonl"
    quarantine_path = tmp_path / "quarantine.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(tmp_path / "missing.jsonl"),
            "--out",
            str(out_path),
            "--quarantine-out",
            str(quarantine_path),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "input not found" in (proc.stdout + proc.stderr)
