"""Tests for parser_v2 dual-run sidecar/report pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.parser_v2.dual_run import run_dual_run


def _write_fixture(path: Path) -> None:
    row = {
        "fixture_id": "FX-DUAL-001",
        "source": {"doc_id": "doc-1", "section_number": "2.14"},
        "text": {
            "raw_text": "(a) First.\n(b) Second.\n(c) Third.\n",
            "char_start": 250,
        },
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_run_dual_run_writes_sidecar_and_report(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures.jsonl"
    sidecar = tmp_path / "sidecar.jsonl"
    _write_fixture(fixtures)

    report = run_dual_run(
        fixtures,
        limit=10,
        sidecar_out=sidecar,
        overwrite_sidecar=True,
    )
    assert report["processed_sections"] == 1
    assert report["sidecar_records"] == 1
    assert report["section_status_counts"]["accepted"] == 1
    assert sidecar.exists()
    lines = sidecar.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["fixture_id"] == "FX-DUAL-001"
    assert payload["parser_v1"]["node_count"] == 3
    assert payload["parser_v2"]["solution"]["section_parse_status"] == "accepted"
    assert "adapted_link_payload" in payload["parser_v2"]
