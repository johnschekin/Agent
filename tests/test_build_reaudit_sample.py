from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_reaudit_sample.py"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _base_row(row_id: str, decision: str) -> dict[str, object]:
    return {
        "row_id": row_id,
        "queue_item_id": row_id,
        "decision": decision,
        "confidence_level": "medium",
    }


def test_build_reaudit_sample_deterministic(tmp_path: Path) -> None:
    batch_a = tmp_path / "batch_a.jsonl"
    batch_b = tmp_path / "batch_b.jsonl"
    _write_jsonl(
        batch_a,
        [_base_row(f"ROW-{i:04d}", "accepted") for i in range(1, 11)],
    )
    _write_jsonl(
        batch_b,
        [_base_row(f"ROW-{i:04d}", "review") for i in range(11, 21)],
    )
    out = tmp_path / "reaudit.jsonl"
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--batch",
        str(batch_a),
        "--batch",
        str(batch_b),
        "--sample-ratio",
        "0.1",
        "--min-sample-size",
        "2",
        "--seed",
        "7",
        "--out",
        str(out),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["sample_row_count"] == 2
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 2
    assert all(row["schema_version"] == "manual-reaudit-sample-v1" for row in rows)
    assert all(row["row_id"] for row in rows)
    assert all(row["re_audit_decision"] == "" for row in rows)


def test_build_reaudit_sample_rejects_bad_ratio(tmp_path: Path) -> None:
    batch = tmp_path / "batch.jsonl"
    _write_jsonl(batch, [_base_row("ROW-0001", "accepted")])
    out = tmp_path / "reaudit.jsonl"
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--batch",
        str(batch),
        "--sample-ratio",
        "0",
        "--out",
        str(out),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "--sample-ratio must be > 0 and <= 1" in (proc.stdout + proc.stderr)
