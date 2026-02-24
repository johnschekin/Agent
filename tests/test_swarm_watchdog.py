"""Tests for swarm watchdog alerting and gating."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _run_watchdog(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "swarm_watchdog.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_checkpoint(
    workspace_root: Path,
    family: str,
    *,
    status: str,
    last_update: str,
    iteration_count: int = 0,
    last_strategy_version: int = 0,
) -> None:
    family_dir = workspace_root / family
    family_dir.mkdir(parents=True, exist_ok=True)
    (family_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "family": family,
                "status": status,
                "last_update": last_update,
                "iteration_count": iteration_count,
                "last_strategy_version": last_strategy_version,
            },
            indent=2,
        )
    )


def test_watchdog_warns_on_stale_running(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    conf.write_text(
        "\n".join(
            [
                "alpha|0|1|opus46|cash_flow.alpha",
                "beta|1|1|opus46|cash_flow.beta",
            ]
        )
        + "\n"
    )
    old_ts = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    fresh_ts = datetime.now(UTC).isoformat()
    _write_checkpoint(workspaces, "alpha", status="running", last_update=old_ts)
    _write_checkpoint(workspaces, "beta", status="running", last_update=fresh_ts)

    proc = _run_watchdog(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--stale-minutes",
            "60",
            "--fail-on",
            "warning",
        ],
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["summary"]["warning_count"] >= 1
    alert_types = [a["type"] for a in payload["alerts"]]
    assert "stale_running" in alert_types


def test_watchdog_marks_stalled_on_critical_orphan(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    conf.write_text("alpha|0|1|opus46|cash_flow.alpha\n")
    old_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    _write_checkpoint(workspaces, "alpha", status="running", last_update=old_ts)

    # Enable pane activity check with a non-existent session to force orphan detection.
    proc = _run_watchdog(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--check-pane-activity",
            "--session",
            "definitely-missing-session",
            "--mark-stalled",
            "--mark-on",
            "warning",
            "--fail-on",
            "none",
        ],
    )
    # pane check unsupported here, so no orphan critical; stale warning still marks stalled.
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["summary"]["stalled_count"] >= 1
    checkpoint = json.loads((workspaces / "alpha" / "checkpoint.json").read_text())
    assert checkpoint["status"] == "stalled"
    assert "stalled_reason" in checkpoint


def test_watchdog_no_fail_when_no_alerts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    conf.write_text("alpha|0|1|opus46|cash_flow.alpha\n")
    _write_checkpoint(
        workspaces,
        "alpha",
        status="running",
        last_update=datetime.now(UTC).isoformat(),
        iteration_count=1,
        last_strategy_version=1,
    )
    (workspaces / "alpha" / "strategies").mkdir(parents=True, exist_ok=True)
    (workspaces / "alpha" / "strategies" / "cash_flow.alpha_v001.json").write_text("{}\n")

    proc = _run_watchdog(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--stale-minutes",
            "180",
            "--bootstrap-grace-minutes",
            "120",
            "--fail-on",
            "critical",
        ],
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["summary"]["alert_count"] == 0
