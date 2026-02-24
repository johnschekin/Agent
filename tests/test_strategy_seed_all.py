"""Tests for strategy_seed_all global seeding script."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_strategy_seed_all_generates_full_coverage(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    ontology_path = tmp_path / "ontology.json"
    bootstrap_path = tmp_path / "bootstrap.json"
    output_path = tmp_path / "seed_bundle.json"
    output_dir = tmp_path / "seed_strategies"

    ontology_payload = {
        "domains": [
            {
                "id": "debt_capacity",
                "name": "Debt Capacity",
                "children": [
                    {
                        "id": "debt_capacity.indebtedness",
                        "name": "Indebtedness",
                        "children": [
                            {
                                "id": "debt_capacity.indebtedness.general_basket",
                                "name": "General Basket",
                                "children": [],
                            },
                            {
                                "id": "debt_capacity.indebtedness.ratio_debt",
                                "name": "Ratio Debt",
                                "children": [],
                            },
                        ],
                    }
                ],
            },
            {
                "id": "other_family",
                "name": "Other Family",
                "children": [
                    {"id": "other_family.special_case", "name": "Special Case", "children": []}
                ],
            },
        ]
    }
    bootstrap_payload = {
        "debt_capacity.indebtedness": {
            "id": "debt_capacity.indebtedness",
            "name": "Indebtedness",
            "search_strategy": {
                "heading_patterns": ["Limitation on Indebtedness"],
                "keyword_anchors": ["indebtedness", "debt"],
            },
        },
        "debt_capacity.indebtedness.general_basket": {
            "id": "debt_capacity.indebtedness.general_basket",
            "name": "General Basket",
            "search_strategy": {
                "heading_patterns": ["General Basket"],
                "keyword_anchors": ["basket", "indebtedness"],
            },
        },
    }

    ontology_path.write_text(json.dumps(ontology_payload, indent=2))
    bootstrap_path.write_text(json.dumps(bootstrap_payload, indent=2))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "strategy_seed_all.py"),
            "--ontology",
            str(ontology_path),
            "--bootstrap",
            str(bootstrap_path),
            "--output",
            str(output_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    summary = json.loads(proc.stdout)
    assert summary["status"] == "ok"
    assert summary["total_ontology_nodes"] == 6
    assert summary["total_seeded"] == 6
    assert summary["invalid_ids"] == []
    assert summary["per_node_files_written"] == 6

    bundle = json.loads(output_path.read_text())
    assert bundle["schema_version"] == "strategy_seed_all_v1"
    assert bundle["total_ontology_nodes"] == 6
    assert bundle["total_seeded"] == 6

    strategies = bundle["strategies"]
    assert set(strategies.keys()) == {
        "debt_capacity",
        "debt_capacity.indebtedness",
        "debt_capacity.indebtedness.general_basket",
        "debt_capacity.indebtedness.ratio_debt",
        "other_family",
        "other_family.special_case",
    }
    assert strategies["debt_capacity.indebtedness.general_basket"]["seed_source"] == "bootstrap"
    assert strategies["debt_capacity.indebtedness.ratio_debt"]["seed_source"] == "derived"
    assert strategies["other_family.special_case"]["seed_source"] == "empty"
