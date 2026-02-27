"""Gold fixtures for clause parser behavioral parity.

These fixtures intentionally lock current parser output for high-risk patterns.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.clause_parser import parse_clauses


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "clause_gold"
EXPECTED_PATH = FIXTURE_DIR / "expected.json"


def _serialize_nodes(text: str) -> list[dict[str, object]]:
    nodes = parse_clauses(text)
    return [
        {
            "id": n.id,
            "label": n.label,
            "parent_id": n.parent_id,
            "depth": n.depth,
            "level_type": n.level_type,
            "xref_suspected": bool(n.xref_suspected),
            "is_structural_candidate": bool(n.is_structural_candidate),
            "parse_confidence": round(float(n.parse_confidence), 4),
            "demotion_reason": n.demotion_reason,
        }
        for n in nodes
    ]


def test_gold_fixture_manifest_exists() -> None:
    assert EXPECTED_PATH.exists(), f"Missing gold manifest: {EXPECTED_PATH}"


def test_gold_fixtures_exact_parity() -> None:
    payload = json.loads(EXPECTED_PATH.read_text())
    assert isinstance(payload, dict)
    assert len(payload) >= 8

    for fixture_name, fixture in payload.items():
        fixture_file = ROOT / str(fixture["file"])
        assert fixture_file.exists(), f"Missing fixture text file: {fixture_file}"
        text = fixture_file.read_text()

        actual = _serialize_nodes(text)
        expected = fixture["nodes"]

        assert actual == expected, (
            f"Gold fixture mismatch for {fixture_name}. "
            f"If intentional, update {EXPECTED_PATH}."
        )
