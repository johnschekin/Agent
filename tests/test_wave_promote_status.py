"""Tests for wave_promote_status checkpoint lifecycle promotion."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_cli(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "wave_promote_status.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_checkpoint(workspaces: Path, family: str, status: str) -> None:
    d = workspaces / family
    d.mkdir(parents=True, exist_ok=True)
    (d / "checkpoint.json").write_text(
        json.dumps({"family": family, "status": status}, indent=2)
    )


def _write_strategy(workspaces: Path, family: str, concept_id: str) -> None:
    p = workspaces / family / "strategies"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{concept_id}_v001.json").write_text(
        json.dumps(
            {
                "concept_id": concept_id,
                "concept_name": concept_id.split(".")[-1],
                "family": concept_id.split(".")[1] if "." in concept_id else concept_id,
                "heading_patterns": ["X"],
                "keyword_anchors": ["x"],
                "concept_specific_keywords": ["x"],
                "version": 1,
            },
            indent=2,
        )
    )


def _write_evidence(workspaces: Path, family: str, concept_id: str, rows: int) -> None:
    p = workspaces / family / "evidence"
    p.mkdir(parents=True, exist_ok=True)
    fp = p / f"{concept_id}_test.jsonl"
    with fp.open("w", encoding="utf-8") as handle:
        for i in range(rows):
            handle.write(
                json.dumps(
                    {
                        "schema_version": "evidence_v2",
                        "ontology_node_id": concept_id,
                        "run_id": "run",
                        "status": "HIT" if i == 0 else "NOT_FOUND",
                    }
                )
                + "\n"
            )


def test_promote_status_dry_run_does_not_mutate(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    conf.write_text(
        "\n".join(
            [
                "alpha|0|1|opus46|a.alpha",
                "beta|1|1|opus46|a.beta",
            ]
        )
        + "\n"
    )
    _write_checkpoint(workspaces, "alpha", "running")
    _write_strategy(workspaces, "alpha", "a.alpha")
    _write_evidence(workspaces, "alpha", "a.alpha", rows=5)

    _write_checkpoint(workspaces, "beta", "running")
    _write_strategy(workspaces, "beta", "a.beta")

    proc = _run_cli(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--wave",
            "1",
            "--require-strategy",
            "--require-evidence",
            "--dry-run",
        ],
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["summary"]["promoted_count"] == 1
    assert payload["summary"]["blocked_count"] == 1

    alpha = json.loads((workspaces / "alpha" / "checkpoint.json").read_text())
    beta = json.loads((workspaces / "beta" / "checkpoint.json").read_text())
    assert alpha["status"] == "running"
    assert beta["status"] == "running"


def test_promote_status_applies_and_unblocks_transition(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    conf.write_text(
        "\n".join(
            [
                "alpha|0|1|opus46|a.alpha",
                "beta|1|1|opus46|a.beta",
                "gamma|0|2|opus46|a.gamma",
            ]
        )
        + "\n"
    )
    for family, cid in [("alpha", "a.alpha"), ("beta", "a.beta")]:
        _write_checkpoint(workspaces, family, "running")
        _write_strategy(workspaces, family, cid)
        _write_evidence(workspaces, family, cid, rows=3)

    promote = _run_cli(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--wave",
            "1",
            "--require-strategy",
            "--require-evidence",
            "--to-status",
            "completed",
            "--note",
            "wave1-bootstrap-complete",
        ],
    )
    assert promote.returncode == 0
    promote_payload = json.loads(promote.stdout)
    assert promote_payload["summary"]["promoted_count"] == 2
    assert promote_payload["summary"]["blocked_count"] == 0

    for family in ("alpha", "beta"):
        payload = json.loads((workspaces / family / "checkpoint.json").read_text())
        assert payload["status"] == "completed"
        assert payload["status_note"] == "wave1-bootstrap-complete"
        assert payload["status_updated_by"] == "wave_promote_status.py"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    gate = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "wave_transition_gate.py"),
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--target-wave",
            "2",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert gate.returncode == 0
    gate_payload = json.loads(gate.stdout)
    assert gate_payload["decision"]["allowed"] is True
