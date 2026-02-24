"""Tests for evidence_collector v2 contract and NOT_FOUND emission."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_collector(root: Path, args: list[str]) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "evidence_collector.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_collector_normalizes_pattern_payload_with_not_found(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    matches_path = tmp_path / "pattern_payload.json"
    payload = {
        "schema_version": "pattern_tester_v2",
        "run_id": "run_123",
        "strategy_version": 7,
        "matches": [
            {
                "doc_id": "doc_hit",
                "section": "7.01",
                "heading": "Limitation on Indebtedness",
                "score": 0.91,
                "match_method": "heading",
                "template_family": "cluster_001",
                "confidence_components": {"heading": 1.0, "keyword": 0.6},
                "confidence_final": 0.88,
                "scope_parity": {"label": "NARROW", "operator_count": 3},
                "preemption": {"override_count": 1, "yield_count": 0},
                "outlier": {"level": "review", "score": 0.47, "flags": ["heading_rare"]},
            }
        ],
        "miss_records": [
            {
                "doc_id": "doc_miss",
                "best_score": 0.24,
                "best_section": "6.03",
                "best_heading": "Investments",
                "template_family": "cluster_002",
                "not_found_reason": "no_section_match_above_threshold",
            }
        ],
    }
    matches_path.write_text(json.dumps(payload))

    summary = _run_collector(
        root,
        [
            "--matches",
            str(matches_path),
            "--concept-id",
            "debt_capacity.indebtedness",
            "--workspace",
            str(workspace),
        ],
    )

    assert summary["schema_version"] == "evidence_v2"
    assert summary["run_id"] == "run_123"
    assert summary["strategy_version"] == 7
    assert summary["hit_records"] == 1
    assert summary["not_found_records"] == 1
    assert isinstance(summary["checkpoint_update"], dict)
    assert summary["checkpoint_update"]["status"] == "running"
    assert summary["checkpoint_update"]["last_strategy_version"] == 7

    evidence_path = Path(str(summary["evidence_file"]))
    rows = [json.loads(line) for line in evidence_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 2
    hit = next(r for r in rows if r["record_type"] == "HIT")
    miss = next(r for r in rows if r["record_type"] == "NOT_FOUND")
    assert hit["ontology_node_id"] == "debt_capacity.indebtedness"
    assert isinstance(hit["confidence_breakdown"], dict)
    assert isinstance(hit["scope_parity"], dict)
    assert isinstance(hit["preemption"], dict)
    assert miss["doc_id"] == "doc_miss"
    assert miss["not_found_reason"] == "no_section_match_above_threshold"

    checkpoint = workspace / "checkpoint.json"
    assert checkpoint.exists()
    checkpoint_payload = json.loads(checkpoint.read_text())
    assert checkpoint_payload["current_concept_id"] == "debt_capacity.indebtedness"
    assert checkpoint_payload["last_evidence_run_id"] == "run_123"
    assert checkpoint_payload["last_strategy_version"] == 7


def test_collector_skip_not_found_filters_records(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    matches_path = tmp_path / "rows.json"
    payload = [
        {"doc_id": "doc1", "record_type": "HIT", "match_type": "keyword", "score": 0.7},
        {"doc_id": "doc2", "record_type": "NOT_FOUND", "not_found_reason": "none"},
    ]
    matches_path.write_text(json.dumps(payload))

    summary = _run_collector(
        root,
        [
            "--matches",
            str(matches_path),
            "--concept-id",
            "debt_capacity.indebtedness",
            "--workspace",
            str(workspace),
            "--skip-not-found",
        ],
    )

    assert summary["records_written"] == 1
    assert summary["hit_records"] == 1
    assert summary["not_found_records"] == 0
    checkpoint_payload = json.loads((workspace / "checkpoint.json").read_text())
    assert checkpoint_payload["last_evidence_records"] == 1
    assert checkpoint_payload["status"] == "running"
