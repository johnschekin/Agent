"""Tests for additive /api/links/intelligence endpoints."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agent.link_store import LinkStore
from dashboard.api import server as dashboard_server


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def test_links_intelligence_signals_and_evidence_scope_filter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspaces"
    monkeypatch.setattr(dashboard_server, "_workspace_root", workspace)
    monkeypatch.setattr(
        dashboard_server,
        "_strategies",
        {
            "debt_capacity.indebtedness": {
                "concept_id": "debt_capacity.indebtedness",
                "concept_name": "Indebtedness",
                "family_id": "debt_capacity.indebtedness",
                "family": "indebtedness",
                "heading_patterns": ["Limitation on Indebtedness"],
                "keyword_anchors": ["indebtedness", "debt"],
                "dna_tier1": ["incurrence test"],
                "dna_tier2": ["other indebtedness"],
                "heading_hit_rate": 0.82,
                "keyword_precision": 0.78,
                "cohort_coverage": 0.74,
                "corpus_prevalence": 0.7,
                "validation_status": "validated",
                "version": 3,
                "last_updated": "2026-02-26T00:00:00Z",
            },
            "cash_flow.inv": {
                "concept_id": "cash_flow.inv",
                "concept_name": "Investments",
                "family_id": "cash_flow.inv",
                "family": "inv",
                "heading_patterns": ["Investments"],
                "keyword_anchors": ["investment"],
                "dna_tier1": ["permitted investments"],
                "dna_tier2": [],
                "heading_hit_rate": 0.75,
                "keyword_precision": 0.7,
                "cohort_coverage": 0.68,
                "corpus_prevalence": 0.66,
                "validation_status": "bootstrap",
                "version": 1,
                "last_updated": "2026-02-20T00:00:00Z",
            },
        },
    )

    evidence_file = workspace / "indebtedness" / "evidence" / "rows.jsonl"
    _write_jsonl(
        evidence_file,
        [
            {
                "ontology_node_id": "debt_capacity.indebtedness",
                "record_type": "HIT",
                "doc_id": "doc_a",
                "template_family": "kirkland",
                "section_number": "6.01",
                "heading": "Limitation on Indebtedness",
                "score": 0.91,
            },
            {
                "ontology_node_id": "debt_capacity.indebtedness",
                "record_type": "NOT_FOUND",
                "doc_id": "doc_b",
                "template_family": "kirkland",
                "section_number": "6.01",
                "heading": "Limitation on Indebtedness",
                "score": 0.15,
            },
            {
                "ontology_node_id": "cash_flow.inv",
                "record_type": "HIT",
                "doc_id": "doc_c",
                "template_family": "cahill",
                "section_number": "7.04",
                "heading": "Investments",
                "score": 0.88,
            },
        ],
    )

    signals = asyncio.run(
        dashboard_server.links_intelligence_signals(
            scope_id="debt_capacity.indebtedness",
            top_n=12,
        )
    )
    assert signals["total_strategies"] == 1
    assert signals["strategies"][0]["concept_id"] == "debt_capacity.indebtedness"
    assert signals["top_keyword_anchors"][0]["value"] == "indebtedness"

    evidence = asyncio.run(
        dashboard_server.links_intelligence_evidence(
            scope_id="debt_capacity.indebtedness",
            record_type="HIT",
            limit=20,
            offset=0,
        )
    )
    assert evidence["summary"]["scope_total"] == 2
    assert evidence["summary"]["scope_hits"] == 1
    assert evidence["summary"]["rows_returned"] == 1
    assert evidence["rows"][0]["concept_id"] == "debt_capacity.indebtedness"
    assert evidence["rows"][0]["record_type"] == "HIT"


def test_links_intelligence_ops_scope_filter(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces"
    monkeypatch.setattr(dashboard_server, "_workspace_root", workspace)
    monkeypatch.setattr(
        dashboard_server,
        "_strategies",
        {
            "debt_capacity.indebtedness": {
                "concept_id": "debt_capacity.indebtedness",
                "concept_name": "Indebtedness",
                "family_id": "debt_capacity.indebtedness",
                "family": "indebtedness",
                "heading_patterns": [],
                "keyword_anchors": [],
                "dna_tier1": [],
                "dna_tier2": [],
            },
            "cash_flow.inv": {
                "concept_id": "cash_flow.inv",
                "concept_name": "Investments",
                "family_id": "cash_flow.inv",
                "family": "inv",
                "heading_patterns": [],
                "keyword_anchors": [],
                "dna_tier1": [],
                "dna_tier2": [],
            },
        },
    )

    _write_json(
        workspace / "indebtedness" / "checkpoint.json",
        {
            "status": "running",
            "iteration_count": 4,
            "current_concept_id": "debt_capacity.indebtedness",
            "last_update": "2026-02-26T00:00:00+00:00",
        },
    )
    _write_json(
        workspace / "inv" / "checkpoint.json",
        {
            "status": "running",
            "iteration_count": 3,
            "current_concept_id": "cash_flow.inv",
            "last_update": "2026-02-26T00:00:00+00:00",
        },
    )

    store = LinkStore(tmp_path / "links.duckdb", create_if_missing=True)
    monkeypatch.setattr(dashboard_server, "_link_store", store)
    store.create_run(
        {
            "run_id": "run_indebtedness",
            "run_type": "apply",
            "family_id": "debt_capacity.indebtedness",
            "scope_mode": "corpus",
            "corpus_version": "test",
            "corpus_doc_count": 10,
            "parser_version": "test",
            "links_created": 8,
            "conflicts_detected": 0,
        }
    )
    store.complete_run("run_indebtedness", {"links_created": 8, "conflicts_detected": 0})

    store.submit_job(
        {
            "job_id": "job_indebtedness",
            "job_type": "batch_run",
            "params": {"family_id": "debt_capacity.indebtedness"},
        }
    )
    claimed = store.claim_job(worker_pid=1111)
    assert claimed is not None
    store.update_job_progress("job_indebtedness", 0.5, "running")

    ops = asyncio.run(
        dashboard_server.links_intelligence_ops(
            scope_id="debt_capacity.indebtedness",
            stale_minutes=60,
            run_limit=10,
            job_limit=10,
        )
    )
    assert ops["agents"]["total"] == 1
    assert ops["agents"]["items"][0]["family"] == "indebtedness"
    assert ops["jobs"]["total"] == 1
    assert ops["jobs"]["items"][0]["scope_id"] == "debt_capacity.indebtedness"
    assert ops["runs"]["total"] == 1
    assert ops["runs"]["items"][0]["scope_id"] == "debt_capacity.indebtedness"
