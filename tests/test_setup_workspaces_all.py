"""Tests for bulk family workspace setup."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _run(
    root: Path,
    args: list[str],
    *,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "setup_workspaces_all.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_setup_workspaces_all_creates_and_skips_existing(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    ontology_path = tmp_path / "ontology.json"
    bootstrap_path = tmp_path / "bootstrap.json"
    workspaces_root = tmp_path / "workspaces"

    _write_json(
        ontology_path,
        {
            "domains": [
                {
                    "id": "debt_capacity",
                    "children": [
                        {
                            "id": "debt_capacity.indebtedness",
                            "type": "family",
                            "name": "Indebtedness",
                            "children": [
                                {"id": "debt_capacity.indebtedness.general_basket"}
                            ],
                        },
                        {
                            "id": "debt_capacity.liens",
                            "type": "family",
                            "name": "Liens",
                            "children": [
                                {"id": "debt_capacity.liens.permitted_liens"}
                            ],
                        },
                    ],
                }
            ]
        },
    )
    _write_json(
        bootstrap_path,
        {
            "strategies": [
                {
                    "concept_id": "debt_capacity.indebtedness.general_basket",
                    "family": "indebtedness",
                },
                {
                    "concept_id": "debt_capacity.liens.permitted_liens",
                    "family": "liens",
                },
                {
                    "concept_id": "vp_only.legacy",
                    "family": "indebtedness",
                },
            ]
        },
    )

    first = _run(
        root,
        [
            "--ontology",
            str(ontology_path),
            "--bootstrap",
            str(bootstrap_path),
            "--workspace-root",
            str(workspaces_root),
        ],
    )
    assert first.returncode == 0, first.stderr
    payload1 = json.loads(first.stdout)
    assert payload1["summary"]["created"] == 2
    assert payload1["summary"]["failed"] == 0
    assert (workspaces_root / "indebtedness" / "context" / "ontology_subtree.json").exists()
    assert (workspaces_root / "liens" / "context" / "ontology_subtree.json").exists()

    second = _run(
        root,
        [
            "--ontology",
            str(ontology_path),
            "--bootstrap",
            str(bootstrap_path),
            "--workspace-root",
            str(workspaces_root),
        ],
    )
    assert second.returncode == 0, second.stderr
    payload2 = json.loads(second.stdout)
    assert payload2["summary"]["created"] == 0
    assert payload2["summary"]["skipped_existing"] == 2
    statuses = {row["status"] for row in payload2["rows"]}
    assert "skipped_existing" in statuses

