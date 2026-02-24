"""Tests for dashboard review operations endpoints."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dashboard.api import server as dashboard_server


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row) for row in rows) + "\n"
    path.write_text(text)


def test_review_strategy_timeline(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces"
    monkeypatch.setattr(dashboard_server, "_workspace_root", workspace)

    concept_id = "debt_capacity.indebtedness"
    strategies_dir = workspace / "indebtedness" / "strategies"

    _write_json(
        strategies_dir / f"{concept_id}_v001.json",
        {
            "concept_id": concept_id,
            "heading_patterns": ["Limitation on Indebtedness"],
            "keyword_anchors": ["indebtedness", "debt"],
            "dna_tier1": ["incurrence test"],
            "dna_tier2": [],
            "heading_hit_rate": 0.75,
            "keyword_precision": 0.7,
            "cohort_coverage": 0.68,
            "_meta": {"note": "baseline"},
        },
    )
    _write_json(
        strategies_dir / f"{concept_id}_v002.json",
        {
            "concept_id": concept_id,
            "heading_patterns": ["Limitation on Indebtedness", "Limitation on Debt"],
            "keyword_anchors": ["indebtedness", "debt", "incurrence"],
            "dna_tier1": ["incurrence test", "negative covenant"],
            "dna_tier2": ["pari passu"],
            "heading_hit_rate": 0.82,
            "keyword_precision": 0.78,
            "cohort_coverage": 0.74,
            "_meta": {"note": "added heading variant", "previous_version": 1},
        },
    )
    _write_json(
        strategies_dir / f"{concept_id}_v002.judge.json",
        {
            "precision_estimate": 0.85,
            "weighted_precision_estimate": 0.9,
            "n_sampled": 20,
        },
    )

    payload = asyncio.run(dashboard_server.review_strategy_timeline(concept_id))
    assert payload["concept_id"] == concept_id
    assert payload["total_versions"] == 2
    assert len(payload["versions"]) == 2

    first, second = payload["versions"]
    assert first["delta"] == {}
    assert second["delta"]["heading_pattern_count"] == 1
    assert second["delta"]["keyword_anchor_count"] == 1
    assert second["delta"]["dna_phrase_count"] == 2
    assert second["judge"]["exists"] is True
    assert second["judge"]["n_sampled"] == 20


def test_review_evidence_and_coverage(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces"
    monkeypatch.setattr(dashboard_server, "_workspace_root", workspace)

    evidence_file = workspace / "indebtedness" / "evidence" / "rows.jsonl"
    _write_jsonl(
        evidence_file,
        [
            {
                "ontology_node_id": "debt_capacity.indebtedness",
                "record_type": "HIT",
                "doc_id": "doc_a",
                "template_family": "kirkland",
                "section_number": "7.01",
                "heading": "Limitation on Indebtedness",
                "score": 0.91,
            },
            {
                "ontology_node_id": "debt_capacity.indebtedness",
                "record_type": "NOT_FOUND",
                "doc_id": "doc_b",
                "template_family": "kirkland",
                "section_number": "",
                "heading": "",
            },
            {
                "ontology_node_id": "debt_capacity.indebtedness",
                "record_type": "HIT",
                "doc_id": "doc_c",
                "template_family": "cahill",
                "section_number": "6.02",
                "heading": "Limitation on Debt",
                "score": 0.78,
            },
            {
                "ontology_node_id": "liens.capacity",
                "record_type": "HIT",
                "doc_id": "doc_d",
                "template_family": "kirkland",
                "section_number": "7.02",
                "heading": "Limitation on Liens",
                "score": 0.88,
            },
        ],
    )

    page1 = asyncio.run(
        dashboard_server.review_evidence(
            concept_id="debt_capacity.indebtedness",
            template_family=None,
            record_type=None,
            limit=1,
            offset=0,
        )
    )
    assert page1["rows_returned"] == 1
    assert page1["rows_matched"] == 3
    assert page1["has_prev"] is False
    assert page1["has_next"] is True

    page2 = asyncio.run(
        dashboard_server.review_evidence(
            concept_id="debt_capacity.indebtedness",
            template_family=None,
            record_type=None,
            limit=1,
            offset=1,
        )
    )
    assert page2["rows_returned"] == 1
    assert page2["has_prev"] is True
    assert page2["has_next"] is True

    hit_only = asyncio.run(
        dashboard_server.review_evidence(
            concept_id="debt_capacity.indebtedness",
            template_family=None,
            record_type="HIT",
            limit=10,
            offset=0,
        )
    )
    assert hit_only["rows_matched"] == 2

    heatmap = asyncio.run(
        dashboard_server.review_coverage_heatmap(
            concept_id="debt_capacity.indebtedness",
            top_concepts=10,
        )
    )
    assert heatmap["concepts"] == ["debt_capacity.indebtedness"]
    cell_map = {
        (c["concept_id"], c["template_family"]): c
        for c in heatmap["cells"]
    }
    kirkland = cell_map[("debt_capacity.indebtedness", "kirkland")]
    assert kirkland["total"] == 2
    assert kirkland["hits"] == 1
    assert kirkland["hit_rate"] == 0.5


def test_review_judge_history_and_agent_activity(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces"
    monkeypatch.setattr(dashboard_server, "_workspace_root", workspace)

    concept_id = "debt_capacity.indebtedness"
    strategies_dir = workspace / "indebtedness" / "strategies"
    _write_json(
        strategies_dir / f"{concept_id}_v001.judge.json",
        {
            "precision_estimate": 0.8,
            "weighted_precision_estimate": 0.85,
            "n_sampled": 20,
            "correct": 16,
            "partial": 2,
            "wrong": 2,
            "generated_at": "2026-02-23T00:00:00Z",
            "run_id": "run_1",
        },
    )
    _write_json(
        strategies_dir / f"{concept_id}_v002.judge.json",
        {
            "precision_estimate": 0.9,
            "weighted_precision_estimate": 0.93,
            "n_sampled": 20,
            "correct": 18,
            "partial": 1,
            "wrong": 1,
            "generated_at": "2026-02-23T01:00:00Z",
            "run_id": "run_2",
        },
    )

    history = asyncio.run(dashboard_server.review_judge_history(concept_id))
    assert history["concept_id"] == concept_id
    assert [row["version"] for row in history["history"]] == [1, 2]

    now = datetime.now(timezone.utc)
    _write_json(
        workspace / "indebtedness" / "checkpoint.json",
        {
            "status": "running",
            "iteration_count": 4,
            "last_update": now.isoformat(),
        },
    )
    _write_json(
        workspace / "liens" / "checkpoint.json",
        {
            "status": "running",
            "iteration_count": 2,
            "last_update": (now - timedelta(hours=2)).isoformat(),
        },
    )

    activity = asyncio.run(dashboard_server.review_agent_activity(stale_minutes=30))
    assert activity["total"] == 2
    assert activity["stale_count"] == 1
