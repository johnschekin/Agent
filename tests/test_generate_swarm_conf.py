"""Tests for ontology-driven swarm config generation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def test_generate_swarm_conf_wave_distribution(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    ontology_path = tmp_path / "ontology.json"
    conf_path = tmp_path / "swarm.conf"
    _write_json(
        ontology_path,
        {
            "domains": [
                {
                    "id": "d1",
                    "children": [
                        {"id": "d1.alpha", "type": "family", "name": "Alpha"},
                        {"id": "d1.beta", "type": "family", "name": "Beta"},
                        {"id": "d1.gamma", "type": "family", "name": "Gamma"},
                    ],
                },
                {
                    "id": "d2",
                    "children": [
                        {"id": "d2.delta", "type": "family", "name": "Delta"},
                        {"id": "d2.epsilon", "type": "family", "name": "Epsilon"},
                        {"id": "d2.zeta", "type": "family", "name": "Zeta"},
                    ],
                },
            ]
        },
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "generate_swarm_conf.py"),
            "--ontology",
            str(ontology_path),
            "--output",
            str(conf_path),
            "--wave1-count",
            "2",
            "--wave2-anchors",
            "d2.delta",
            "--wave4-families",
            "d2.zeta",
            "--panes",
            "2",
            "--force",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["assignment_count"] == 6
    assert payload["summary"]["wave1_count"] == 2
    assert payload["summary"]["wave2_count"] == 1
    assert payload["summary"]["wave4_count"] == 1
    assert payload["summary"]["wave3_count"] == 2

    by_id = {row["family_id"]: row for row in payload["assignments"]}
    assert by_id["d2.delta"]["wave"] == 2
    assert by_id["d2.zeta"]["wave"] == 4
    assert by_id["d2.delta"]["whitelist"] == "d2.delta,d2.delta.*"

    lines = [
        line.strip()
        for line in conf_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#") and "|" in line
    ]
    assert len(lines) == 6
    assert any("delta|" in line and "|2|" in line for line in lines)

