"""Tests for strategy_writer concept whitelist enforcement."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_cli(root: Path, args: list[str], *, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "strategy_writer.py"), *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_strategy_writer_rejects_out_of_scope_concept_and_logs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    strategy_path = tmp_path / "updated.json"
    strategy_path.write_text(
        json.dumps(
            {
                "concept_id": "debt_capacity.indebtedness",
                "concept_name": "Indebtedness",
                "family": "indebtedness",
                "heading_patterns": ["Limitation on Indebtedness"],
                "keyword_anchors": ["indebtedness"],
            },
            indent=2,
        )
    )

    proc = _run_cli(
        root,
        [
            "--concept-id",
            "debt_capacity.indebtedness",
            "--workspace",
            str(workspace),
            "--strategy",
            str(strategy_path),
            "--skip-regression",
        ],
        env_extra={"AGENT_CONCEPT_WHITELIST": "asset_protection.liens"},
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "rejected"
    assert "whitelist" in str(payload["reason"]).lower()

    log_path = workspace / "out_of_scope_discoveries.jsonl"
    assert log_path.exists()
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert rows
    assert rows[0]["schema_version"] == "out_of_scope_discovery_v1"
    assert rows[0]["concept_id"] == "debt_capacity.indebtedness"


def test_strategy_writer_accepts_when_concept_in_whitelist(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    strategy_path = tmp_path / "updated.json"
    strategy_path.write_text(
        json.dumps(
            {
                "concept_id": "debt_capacity.indebtedness",
                "concept_name": "Indebtedness",
                "family": "indebtedness",
                "heading_patterns": ["Limitation on Indebtedness"],
                "keyword_anchors": ["indebtedness"],
            },
            indent=2,
        )
    )

    proc = _run_cli(
        root,
        [
            "--concept-id",
            "debt_capacity.indebtedness",
            "--workspace",
            str(workspace),
            "--strategy",
            str(strategy_path),
            "--skip-regression",
            "--concept-whitelist",
            "debt_capacity.indebtedness,debt_capacity.indebtedness.general_basket",
        ],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "saved"
    assert payload["concept_whitelist"]["enabled"] is True


def test_strategy_writer_accepts_prefix_wildcard_whitelist(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    strategy_path = tmp_path / "updated.json"
    strategy_path.write_text(
        json.dumps(
            {
                "concept_id": "debt_capacity.indebtedness.general_basket",
                "concept_name": "General Basket",
                "family": "indebtedness",
                "heading_patterns": ["General Debt Basket"],
                "keyword_anchors": ["indebtedness"],
            },
            indent=2,
        )
    )

    proc = _run_cli(
        root,
        [
            "--concept-id",
            "debt_capacity.indebtedness.general_basket",
            "--workspace",
            str(workspace),
            "--strategy",
            str(strategy_path),
            "--skip-regression",
            "--concept-whitelist",
            "debt_capacity.indebtedness.*",
        ],
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "saved"
    assert payload["concept_whitelist"]["enabled"] is True
    assert payload["concept_whitelist"]["prefix_count"] == 1
