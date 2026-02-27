from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.clause_parser import parse_clauses


def _gold_nodes_from_text(text: str, *, char_start: int = 0) -> list[dict[str, object]]:
    nodes = parse_clauses(text, global_offset=char_start)
    out: list[dict[str, object]] = []
    for node in nodes:
        span_start = int(node.span_start)
        span_end = int(node.span_end)
        if span_end < span_start:
            span_end = span_start
        out.append(
            {
                "clause_id": node.id,
                "label": node.label,
                "parent_id": node.parent_id,
                "depth": node.depth,
                "level_type": node.level_type,
                "span_start": span_start,
                "span_end": span_end,
                "is_structural": bool(node.is_structural_candidate),
                "xref_suspected": bool(node.xref_suspected),
                "confidence_band": "high",
            },
        )
    return out


def _make_fixture(
    *,
    fixture_id: str,
    category: str,
    decision: str,
    raw_text: str,
    reason_codes: list[str],
    char_start: int = 0,
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "schema_version": "gold-fixture-v1",
        "category": category,
        "source_type": "synthetic",
        "source": {
            "doc_id": f"doc-{fixture_id}",
            "section_number": "1.01",
            "snapshot_id": "test-snapshot",
            "candidate_score": 1.0,
        },
        "text": {
            "raw_text": raw_text,
            "char_start": char_start,
            "char_end": char_start + len(raw_text),
            "normalization": {"engine": "test", "version": "v1"},
        },
        "section_meta": {
            "heading": "Test Heading",
            "article_num": 1,
            "word_count": 10,
        },
        "gold_nodes": _gold_nodes_from_text(raw_text, char_start=char_start),
        "gold_decision": decision,
        "reason_codes": reason_codes,
        "adjudication": {
            "human_verified": False,
            "ambiguity_class": "none",
            "adjudicator_id": "test",
            "adjudicated_at": None,
            "rationale": "test fixture",
        },
        "split": "train",
        "tags": ["test"],
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_thresholds(path: Path) -> None:
    payload = {
        "decision_policies": {
            "accepted": {
                "min_node_recall": 1.0,
                "min_node_precision": 1.0,
                "max_field_mismatch_ratio": 0.0,
                "max_span_mismatch_ratio": 0.0,
                "max_missing_nodes": 0,
                "max_extra_nodes": 0,
                "span_tolerance": 0,
                "require_abstain_signal": False,
                "abstain_confidence_threshold": 0.5,
            },
            "review": {
                "min_node_recall": 0.8,
                "min_node_precision": 0.6,
                "max_field_mismatch_ratio": 0.3,
                "max_span_mismatch_ratio": 0.3,
                "max_missing_nodes": 20,
                "max_extra_nodes": 20,
                "span_tolerance": 16,
                "require_abstain_signal": False,
                "abstain_confidence_threshold": 0.5,
            },
            "abstain": {
                "min_node_recall": 0.8,
                "min_node_precision": 0.6,
                "max_field_mismatch_ratio": 0.3,
                "max_span_mismatch_ratio": 0.3,
                "max_missing_nodes": 20,
                "max_extra_nodes": 20,
                "span_tolerance": 16,
                "require_abstain_signal": True,
                "abstain_confidence_threshold": 0.5,
            },
        },
        "failure_budgets": {
            "by_decision": {
                "accepted": 0,
                "review": 10,
                "abstain": 10,
            },
            "by_category": {
                "default": 10,
                "overrides": {},
            },
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _run_gate(fixtures_path: Path, thresholds_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/replay_gold_fixtures.py",
            "--fixtures",
            str(fixtures_path),
            "--thresholds",
            str(thresholds_path),
            "--json",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_replay_gold_fixtures_passes_for_matching_fixture(tmp_path: Path) -> None:
    fixtures_path = tmp_path / "fixtures.jsonl"
    thresholds_path = tmp_path / "thresholds.json"

    fixture = _make_fixture(
        fixture_id="FX-001",
        category="linking_contract",
        decision="accepted",
        raw_text="(a) First clause.\n(b) Second clause.\n",
        reason_codes=["INFO_CONTROL_POSITIVE"],
    )
    _write_jsonl(fixtures_path, [fixture])
    _write_thresholds(thresholds_path)

    proc = _run_gate(fixtures_path, thresholds_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "pass"
    assert payload["summary"]["fixtures_failed"] == 0


def test_replay_gold_fixtures_fails_when_accepted_regresses(tmp_path: Path) -> None:
    fixtures_path = tmp_path / "fixtures.jsonl"
    thresholds_path = tmp_path / "thresholds.json"

    fixture = _make_fixture(
        fixture_id="FX-002",
        category="linking_contract",
        decision="accepted",
        raw_text="(a) First clause.\n(b) Second clause.\n",
        reason_codes=["INFO_CONTROL_POSITIVE"],
    )
    # Force an accepted mismatch by corrupting depth on the first node.
    fixture["gold_nodes"][0]["depth"] = int(fixture["gold_nodes"][0]["depth"]) + 1

    _write_jsonl(fixtures_path, [fixture])
    _write_thresholds(thresholds_path)

    proc = _run_gate(fixtures_path, thresholds_path)
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    assert payload["summary"]["fixtures_failed"] == 1
    breaches = payload["budget_breaches"]
    assert any(
        row["scope"] == "decision" and row["key"] == "accepted"
        for row in breaches
    )
