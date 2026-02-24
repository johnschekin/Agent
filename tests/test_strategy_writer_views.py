"""Tests for strategy_writer raw/resolved persistence views."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_strategy_writer_persists_raw_and_resolved_views(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    strategies_dir = workspace / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)

    # Parent family strategy used for inheritance resolution.
    parent_path = strategies_dir / "debt_capacity.indebtedness_v001.json"
    parent_path.write_text(
        json.dumps(
            {
                "concept_id": "debt_capacity.indebtedness",
                "concept_name": "Indebtedness",
                "family": "indebtedness",
                "profile_type": "family_core",
                "heading_patterns": ["Limitation on Indebtedness"],
                "keyword_anchors": ["indebtedness"],
            },
            indent=2,
        )
    )

    updated_path = tmp_path / "updated_child.json"
    updated_path.write_text(
        json.dumps(
            {
                "concept_id": "debt_capacity.indebtedness.general_basket",
                "concept_name": "General Basket",
                "family": "indebtedness",
                "profile_type": "concept_standard",
                "inherits_from": "debt_capacity.indebtedness",
                "heading_patterns": ["General Basket"],
            },
            indent=2,
        )
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "strategy_writer.py"),
            "--concept-id",
            "debt_capacity.indebtedness.general_basket",
            "--workspace",
            str(workspace),
            "--strategy",
            str(updated_path),
            "--note",
            "inheritance test",
            "--skip-regression",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["status"] == "saved"
    assert isinstance(payload.get("checkpoint_update"), dict)
    assert payload["checkpoint_update"]["status"] == "running"
    assert payload["checkpoint_update"]["last_strategy_version"] == 1

    raw_view = Path(payload["raw_view_path"])
    resolved_view = Path(payload["resolved_view_path"])
    assert raw_view.exists()
    assert resolved_view.exists()

    raw_obj = json.loads(raw_view.read_text())
    resolved_obj = json.loads(resolved_view.read_text())
    assert raw_obj["inherits_from"] == "debt_capacity.indebtedness"
    # Inherited keyword anchors should be present only in resolved view.
    assert "keyword_anchors" not in raw_obj
    assert resolved_obj["keyword_anchors"] == ["indebtedness"]
    assert resolved_obj["heading_patterns"] == ["General Basket"]

    checkpoint = workspace / "checkpoint.json"
    assert checkpoint.exists()
    checkpoint_payload = json.loads(checkpoint.read_text())
    assert checkpoint_payload["current_concept_id"] == "debt_capacity.indebtedness.general_basket"
    assert checkpoint_payload["last_strategy_version"] == 1
    assert checkpoint_payload["iteration_count"] == 1
