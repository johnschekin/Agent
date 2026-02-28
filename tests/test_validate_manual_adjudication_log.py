from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_manual_adjudication_log.py"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _base_row() -> dict[str, object]:
    section_text = "Section 1.01 Definitions."
    section_hash = _hash(section_text)
    corpus_build_id = "ray_v2_corpus_build_20260227T041350Z_4e318cf8"
    return {
        "schema_version": "manual-adjudication-log-v1",
        "adjudication_id": "ADJ-0001",
        "row_id": "ROW-0001",
        "queue_item_id": "Q-0001",
        "fixture_id": "FX-0001",
        "doc_id": "doc-1",
        "section_number": "1.01",
        "edge_case_class": "ambiguous_alpha_roman",
        "witness_snippets": ["Section 1.01 Definitions."],
        "candidate_interpretations": {
            "A": {
                "interpretation": "Treat as structural heading",
                "survives": False,
                "reason": "Matches table-of-contents style reference.",
            },
            "B": {
                "interpretation": "Treat as citation/continuation",
                "survives": True,
                "reason": "Inline reference context dominates.",
            },
        },
        "decision": "review",
        "decision_rationale": "The section marker appears in citation context and is ambiguous.",
        "confidence_level": "medium",
        "adjudicator_id": "johnchtchekine",
        "adjudicated_at": "2026-02-27T13:00:00+00:00",
        "corpus_build_id": corpus_build_id,
        "section_text_sha256": section_hash,
        "doc_text_sha256": section_hash,
        "source_snapshot_id": f"{corpus_build_id}:{section_hash}",
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _run_validator(
    path: Path,
    *,
    enforce_gl1_thresholds: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT), "--log", str(path), "--json"]
    if enforce_gl1_thresholds:
        cmd.append("--enforce-gl1-thresholds")
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_manual_adjudication_validator_passes_for_valid_row(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    _write_jsonl(path, [_base_row()])
    proc = _run_validator(path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "pass"
    assert payload["summary"]["error_count"] == 0


def test_manual_adjudication_validator_fails_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    row = _base_row()
    row.pop("decision_rationale")
    _write_jsonl(path, [row])
    proc = _run_validator(path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    assert any(err["reason_code"] == "E_REQUIRED_FIELD" for err in payload["errors"])


def test_manual_adjudication_validator_fails_snapshot_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    row = _base_row()
    row["source_snapshot_id"] = "bad:snapshot"
    _write_jsonl(path, [row])
    proc = _run_validator(path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert any(err["reason_code"] == "E_SOURCE_SNAPSHOT_ID" for err in payload["errors"])


def test_manual_adjudication_validator_gl1_threshold_check(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    _write_jsonl(path, [_base_row()])
    proc = _run_validator(path, enforce_gl1_thresholds=True)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    assert payload["gl1_failures"]


def test_manual_adjudication_validator_fails_duplicate_rationale(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    row1 = _base_row()
    row2 = _base_row()
    row2["row_id"] = "ROW-0002"
    row2["adjudication_id"] = "ADJ-0002"
    row2["queue_item_id"] = "Q-0002"
    row2["fixture_id"] = "FX-0002"
    _write_jsonl(path, [row1, row2])
    proc = _run_validator(path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert any(
        err["reason_code"] == "E_DUPLICATE_DECISION_RATIONALE"
        for err in payload["errors"]
    )


def test_manual_adjudication_validator_fails_all_review_collapse(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    rows: list[dict[str, object]] = []
    for i in range(10):
        row = _base_row()
        row["row_id"] = f"ROW-{i:04d}"
        row["adjudication_id"] = f"ADJ-{i:04d}"
        row["queue_item_id"] = f"Q-{i:04d}"
        row["fixture_id"] = f"FX-{i:04d}"
        row["decision_rationale"] = (
            f"Row {i}: unresolved conflict between structure and citation in local span."
        )
        rows.append(row)

    _write_jsonl(path, rows)
    proc = _run_validator(path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert any(
        err["reason_code"] == "E_ALL_REVIEW_DECISIONS"
        for err in payload["errors"]
    )
