"""CLI smoke tests for tool availability.

This is a lightweight gate that all pilot tools at least parse args and render
help text. Full 30K behavioral checks run outside unit tests.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = [
    "corpus_search.py",
    "section_reader.py",
    "sample_selector.py",
    "metadata_reader.py",
    "pattern_tester.py",
    "coverage_reporter.py",
    "heading_discoverer.py",
    "structural_mapper.py",
    "dna_discoverer.py",
    "definition_finder.py",
    "child_locator.py",
    "evidence_collector.py",
    "strategy_writer.py",
    "strategy_seed_all.py",
    "setup_workspace.py",
    "setup_workspaces_all.py",
    "template_classifier.py",
    "generate_swarm_conf.py",
    "corpus_profiler.py",
    "benchmark_pipeline.py",
    "check_corpus_v2.py",
    "migrate_v2_did_not_find_policy.py",
    "migrate_strategy_v1_to_v2.py",
    "llm_judge.py",
    "export_labeled_data.py",
    "wave_scheduler.py",
    "swarm_run_ledger.py",
    "swarm_watchdog.py",
    "swarm_artifact_manifest.py",
    "swarm_ops_snapshot.py",
    "wave_transition_gate.py",
    "wave_promote_status.py",
]


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_tool_help(script_name: str) -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / script_name), "--help"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout.lower()
