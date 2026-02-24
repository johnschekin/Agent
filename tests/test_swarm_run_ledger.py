"""Tests for swarm run ledger snapshots."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _run_cli(root: Path, args: list[str]) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "swarm_run_ledger.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _write_checkpoint(workspaces: Path, family: str, payload: dict[str, object]) -> None:
    d = workspaces / family
    d.mkdir(parents=True, exist_ok=True)
    (d / "checkpoint.json").write_text(json.dumps(payload, indent=2))


def test_swarm_run_ledger_summary_and_workspace_counts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"

    conf.write_text(
        "\n".join(
            [
                "SESSION_NAME=test-swarm",
                "alpha|0|1|opus46|cash_flow.alpha,cash_flow.alpha.*",
                "beta|1|1|opus46|cash_flow.beta,cash_flow.beta.*|alpha",
            ]
        )
        + "\n"
    )

    stale_ts = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    _write_checkpoint(
        workspaces,
        "alpha",
        {
            "family": "alpha",
            "status": "running",
            "iteration_count": 4,
            "last_strategy_version": 2,
            "last_update": stale_ts,
            "current_concept_id": "cash_flow.alpha.main",
        },
    )
    alpha_ws = workspaces / "alpha"
    (alpha_ws / "evidence").mkdir(parents=True, exist_ok=True)
    (alpha_ws / "evidence" / "cash_flow.alpha_2026-02-23.jsonl").write_text("{}\n")
    (alpha_ws / "strategies").mkdir(parents=True, exist_ok=True)
    (alpha_ws / "strategies" / "cash_flow.alpha.main_v002.json").write_text("{}\n")
    (alpha_ws / "results").mkdir(parents=True, exist_ok=True)
    (alpha_ws / "results" / "latest_pattern_tester.json").write_text("{}\n")

    fresh_ts = datetime.now(UTC).isoformat()
    _write_checkpoint(
        workspaces,
        "beta",
        {
            "family": "beta",
            "status": "completed",
            "iteration_count": 7,
            "last_strategy_version": 5,
            "last_update": fresh_ts,
        },
    )

    payload = _run_cli(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--stale-minutes",
            "60",
        ],
    )

    summary = payload["summary"]
    assert summary["assignments"] == 2
    assert summary["checkpoint_status_counts"]["running"] == 1
    assert summary["checkpoint_status_counts"]["completed"] == 1
    assert summary["stale_running_count"] == 1
    assert summary["with_evidence_count"] == 1
    assert summary["with_strategy_version_count"] == 1

    rows = payload["rows"]
    alpha = next(row for row in rows if row["family"] == "alpha")
    beta = next(row for row in rows if row["family"] == "beta")
    assert alpha["checkpoint_is_stale_running"] is True
    assert alpha["checkpoint_iteration_count"] == 4
    assert alpha["checkpoint_last_strategy_version"] == 2
    assert alpha["evidence_file_count"] == 1
    assert alpha["strategy_version_file_count"] == 1
    assert alpha["checkpoint_current_concept_id"] == "cash_flow.alpha.main"
    assert beta["checkpoint_status"] == "completed"
    assert beta["checkpoint_is_stale_running"] is False


def test_swarm_run_ledger_wave_filter(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    conf = tmp_path / "swarm.conf"
    workspaces = tmp_path / "workspaces"
    conf.write_text(
        "\n".join(
            [
                "alpha|0|1|opus46|cash_flow.alpha",
                "beta|1|2|opus46|cash_flow.beta",
            ]
        )
        + "\n"
    )

    _write_checkpoint(
        workspaces,
        "alpha",
        {"family": "alpha", "status": "running", "last_update": datetime.now(UTC).isoformat()},
    )
    _write_checkpoint(
        workspaces,
        "beta",
        {"family": "beta", "status": "missing", "last_update": datetime.now(UTC).isoformat()},
    )

    payload = _run_cli(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
            "--wave",
            "1",
        ],
    )
    assert payload["summary"]["assignments"] == 1
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["family"] == "alpha"
