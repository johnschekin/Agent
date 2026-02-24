"""Tests for consolidated swarm ops snapshots."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _run_snapshot(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "swarm_ops_snapshot.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_checkpoint(workspaces: Path, family: str, status: str) -> None:
    family_dir = workspaces / family
    family_dir.mkdir(parents=True, exist_ok=True)
    (family_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "family": family,
                "status": status,
                "last_update": datetime.now(UTC).isoformat(),
                "iteration_count": 1,
                "last_strategy_version": 1,
            },
            indent=2,
        )
    )


def test_ops_snapshot_success_without_transition_gate_requirement(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    plans = tmp_path / "plans"
    conf.write_text("alpha|0|1|opus46|cash_flow.alpha\n")
    _write_checkpoint(workspaces, "alpha", "running")
    alpha = workspaces / "alpha"
    (alpha / "strategies").mkdir(parents=True, exist_ok=True)
    (alpha / "strategies" / "cash_flow.alpha_v001.json").write_text("{}\n")

    proc = _run_snapshot(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--wave",
            "1",
            "--plans-dir",
            str(plans),
        ],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["decision"]["allowed"] is True
    artifacts = payload["artifacts"]
    assert Path(artifacts["ledger"]).exists()
    assert Path(artifacts["watchdog"]).exists()
    assert Path(artifacts["artifact_manifest"]).exists()


def test_ops_snapshot_blocks_when_transition_required_and_not_allowed(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    plans = tmp_path / "plans"
    conf.write_text(
        "\n".join(
            [
                "alpha|0|1|opus46|cash_flow.alpha",
                "beta|0|2|opus46|cash_flow.beta",
            ]
        )
        + "\n"
    )
    _write_checkpoint(workspaces, "alpha", "running")

    proc = _run_snapshot(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--wave",
            "1",
            "--next-wave",
            "2",
            "--plans-dir",
            str(plans),
            "--require-next-wave-allowed",
        ],
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["decision"]["allowed"] is False
    assert payload["decision"]["blocking_reasons"]
    assert Path(payload["artifacts"]["transition_gate"]).exists()
