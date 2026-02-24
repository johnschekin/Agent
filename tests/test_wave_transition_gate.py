"""Tests for wave transition gate checks."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _run_gate(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "wave_transition_gate.py"), *args],
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
        json.dumps(
            {
                "family": family,
                "status": status,
                "last_update": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
    )


def test_transition_gate_blocks_wave2_when_wave1_incomplete(tmp_path: Path) -> None:
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
    _write_checkpoint(workspaces, "alpha", "completed")
    _write_checkpoint(workspaces, "beta", "running")

    proc = _run_gate(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--target-wave",
            "2",
        ],
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["decision"]["allowed"] is False
    assert payload["summary"]["blocked_count"] == 1
    assert payload["blocked"][0]["family"] == "beta"


def test_transition_gate_allows_with_waiver(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    waiver = tmp_path / "waiver.json"
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
    _write_checkpoint(workspaces, "alpha", "completed")
    _write_checkpoint(workspaces, "beta", "running")
    waiver.write_text(
        json.dumps(
            {
                "waived_families": [
                    {"family": "beta", "reason": "manual_waiver_for_canary_rollout"}
                ]
            },
            indent=2,
        )
    )

    proc = _run_gate(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--target-wave",
            "2",
            "--waiver-file",
            str(waiver),
        ],
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["decision"]["allowed"] is True
    assert payload["summary"]["waived_count"] == 1


def test_transition_gate_wave1_has_no_prereq_blockers(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    conf.write_text("alpha|0|1|opus46|a.alpha\n")

    proc = _run_gate(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(tmp_path / "workspaces"),
            "--target-wave",
            "1",
        ],
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["decision"]["allowed"] is True
    assert payload["summary"]["prerequisite_assignments"] == 0
