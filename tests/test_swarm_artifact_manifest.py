"""Tests for swarm artifact manifest snapshots."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _run_manifest(root: Path, args: list[str]) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "swarm_artifact_manifest.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _write_checkpoint(workspaces: Path, family: str, status: str, last_update: str) -> None:
    family_dir = workspaces / family
    family_dir.mkdir(parents=True, exist_ok=True)
    (family_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "family": family,
                "status": status,
                "last_update": last_update,
                "iteration_count": 2,
                "last_strategy_version": 1,
            },
            indent=2,
        )
    )


def test_manifest_counts_strategy_evidence_judge(tmp_path: Path) -> None:
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
    _write_checkpoint(
        workspaces,
        "alpha",
        status="running",
        last_update=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
    )
    alpha = workspaces / "alpha"
    (alpha / "strategies").mkdir(parents=True, exist_ok=True)
    (alpha / "strategies" / "cash_flow.alpha_v001.json").write_text("{}\n")
    (alpha / "strategies" / "cash_flow.alpha_v001.raw.json").write_text("{}\n")
    (alpha / "strategies" / "cash_flow.alpha_v001.resolved.json").write_text("{}\n")
    (alpha / "strategies" / "cash_flow.alpha_v001.judge.json").write_text("{}\n")
    (alpha / "evidence").mkdir(parents=True, exist_ok=True)
    (alpha / "evidence" / "cash_flow.alpha_20260223T000000.jsonl").write_text(
        "{}\n{}\n"
    )
    (alpha / "results").mkdir(parents=True, exist_ok=True)
    (alpha / "results" / "latest.json").write_text("{}\n")

    _write_checkpoint(
        workspaces,
        "beta",
        status="missing",
        last_update="",
    )

    payload = _run_manifest(
        root,
        [
            "--conf",
            str(conf),
            "--workspace-root",
            str(workspaces),
        ],
    )
    summary = payload["summary"]
    assert summary["families_evaluated"] == 2
    assert summary["with_strategy_count"] == 1
    assert summary["with_evidence_count"] == 1
    assert summary["with_judge_count"] == 1
    assert summary["review_ready_count"] == 1
    assert summary["total_evidence_records"] == 2

    rows = payload["rows"]
    alpha_row = next(r for r in rows if r["family"] == "alpha")
    beta_row = next(r for r in rows if r["family"] == "beta")
    assert alpha_row["review_ready"] is True
    assert alpha_row["evidence_record_count"] == 2
    assert alpha_row["judge_report_count"] == 1
    assert alpha_row["family_state"] in {"in_progress", "review_ready"}
    assert beta_row["review_ready"] is False


def test_manifest_wave_filter(tmp_path: Path) -> None:
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
    _write_checkpoint(workspaces, "alpha", status="running", last_update=datetime.now(UTC).isoformat())
    _write_checkpoint(workspaces, "beta", status="running", last_update=datetime.now(UTC).isoformat())

    payload = _run_manifest(
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
    assert payload["summary"]["families_evaluated"] == 1
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["family"] == "alpha"
