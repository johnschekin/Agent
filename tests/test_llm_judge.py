"""Tests for llm_judge CLI."""
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
        [sys.executable, str(root / "scripts" / "llm_judge.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_llm_judge_heuristic_outputs_metrics(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    matches_path = tmp_path / "matches.json"
    out_path = tmp_path / "judge.json"
    matches_path.write_text(
        json.dumps(
            [
                {
                    "doc_id": "d1",
                    "section_path": "7.01",
                    "heading": "Limitation on Indebtedness",
                    "clause_text": "The Borrower shall not incur Indebtedness except as permitted debt.",
                },
                {
                    "doc_id": "d2",
                    "section_path": "7.06",
                    "heading": "Restricted Payments",
                    "clause_text": "The Borrower shall not make Restricted Payments except as permitted.",
                },
                {
                    "doc_id": "d3",
                    "section_path": "7.02",
                    "heading": "Investments",
                    "clause_text": "The Borrower may make Investments under this Section.",
                },
            ]
        )
    )

    payload = _run_cli(
        root,
        [
            "--matches",
            str(matches_path),
            "--concept-id",
            "debt_capacity.indebtedness",
            "--sample",
            "3",
            "--seed",
            "7",
            "--backend",
            "heuristic",
            "--output",
            str(out_path),
        ],
    )

    assert payload["schema_version"] == "llm_judge_v1"
    assert payload["status"] == "ok"
    assert payload["n_candidates"] == 3
    assert payload["n_sampled"] == 3
    assert 0.0 <= float(payload["precision_estimate"]) <= 1.0
    assert "sample_results" in payload
    assert out_path.exists()


def test_llm_judge_mock_uses_expected_verdict(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    matches_path = tmp_path / "matches.jsonl"
    matches_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "doc_id": "d1",
                        "clause_text": "ignored",
                        "expected_verdict": "correct",
                    }
                ),
                json.dumps(
                    {
                        "doc_id": "d2",
                        "clause_text": "ignored",
                        "expected_verdict": "wrong",
                    }
                ),
            ]
        )
        + "\n"
    )

    payload = _run_cli(
        root,
        [
            "--matches",
            str(matches_path),
            "--concept-id",
            "debt_capacity.indebtedness",
            "--sample",
            "2",
            "--backend",
            "mock",
        ],
    )

    assert payload["n_sampled"] == 2
    assert payload["correct"] == 1
    assert payload["wrong"] == 1
    assert payload["partial"] == 0
