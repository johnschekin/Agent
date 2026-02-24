"""Tests for wave_scheduler dependency-aware queueing."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_cli(root: Path, args: list[str]) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "wave_scheduler.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _write_checkpoint(workspaces: Path, family: str, status: str) -> None:
    d = workspaces / family
    d.mkdir(parents=True, exist_ok=True)
    (d / "checkpoint.json").write_text(
        json.dumps({"family": family, "status": status}, indent=2)
    )


def test_wave_scheduler_ready_mode_blocks_on_dependency(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    conf.write_text(
        "\n".join(
            [
                "SESSION_NAME=test",
                "alpha|0|1|opus46|a.alpha",
                "beta|1|1|opus46|a.beta|alpha",
            ]
        )
        + "\n"
    )
    _write_checkpoint(workspaces, "alpha", "initialized")
    _write_checkpoint(workspaces, "beta", "initialized")

    payload = _run_cli(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--wave",
            "1",
            "--mode",
            "ready",
        ],
    )
    selected = [row["family"] for row in payload["selected"]]
    blocked = [row["family"] for row in payload["blocked"]]
    assert "alpha" in selected
    assert "beta" in blocked


def test_wave_scheduler_failed_mode_targets_failed_only(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    conf.write_text(
        "\n".join(
            [
                "SESSION_NAME=test",
                "alpha|0|1|opus46|a.alpha",
                "beta|1|1|opus46|a.beta",
                "gamma|2|1|opus46|a.gamma",
            ]
        )
        + "\n"
    )
    _write_checkpoint(workspaces, "alpha", "completed")
    _write_checkpoint(workspaces, "beta", "failed")
    _write_checkpoint(workspaces, "gamma", "running")

    payload = _run_cli(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--wave",
            "1",
            "--mode",
            "failed",
        ],
    )
    selected = [row["family"] for row in payload["selected"]]
    assert selected == ["beta"]
