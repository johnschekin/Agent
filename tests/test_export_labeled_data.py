"""Tests for labeled data export pipeline."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_cli(root: Path, args: list[str]) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "export_labeled_data.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_export_labeled_data_jsonl_and_lineage(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_file = evidence_dir / "sample.jsonl"
    evidence_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "evidence_v2",
                        "record_type": "HIT",
                        "ontology_node_id": "debt_capacity.indebtedness",
                        "doc_id": "d1",
                        "section_number": "7.01",
                        "clause_path": "7.01.(a)",
                        "char_start": 10,
                        "char_end": 50,
                        "run_id": "run1",
                        "strategy_version": 3,
                    }
                ),
                json.dumps(
                    {
                        "schema_version": "evidence_v2",
                        "record_type": "HIT",
                        "ontology_node_id": "debt_capacity.indebtedness",
                        "doc_id": "d1",
                        "section_number": "7.01",
                        "clause_path": "7.01.(a)",
                        "char_start": 10,
                        "char_end": 50,
                        "run_id": "run1",
                        "strategy_version": 3,
                    }
                ),
                json.dumps(
                    {
                        "schema_version": "evidence_v2",
                        "record_type": "NOT_FOUND",
                        "ontology_node_id": "debt_capacity.indebtedness",
                        "doc_id": "d2",
                    }
                ),
            ]
        )
        + "\n"
    )

    output_prefix = tmp_path / "labeled_data"
    payload = _run_cli(
        root,
        [
            "--inputs",
            str(evidence_dir),
            "--output-prefix",
            str(output_prefix),
            "--format",
            "both",
            "--dedupe",
        ],
    )

    assert payload["schema_version"] == "labeled_export_v1"
    assert payload["rows_exported"] == 1
    assert payload["deduped_rows"] == 1
    jsonl_path = Path(str(payload["jsonl_path"]))
    assert jsonl_path.exists()
    line = json.loads(jsonl_path.read_text().strip().splitlines()[0])
    assert line["record_type"] == "HIT"
    assert "lineage" in line
    assert line["lineage"]["export_run_id"] == payload["export_run_id"]
    if payload["status"] == "ok":
        assert Path(str(payload["parquet_path"])).exists()
    else:
        assert payload["status"] == "partial"
        assert payload["parquet_error"]
