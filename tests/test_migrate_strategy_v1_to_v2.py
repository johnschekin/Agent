"""Tests for migrate_strategy_v1_to_v2 utility."""
from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path
from typing import Any


def _load_module() -> Any:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "migrate_strategy_v1_to_v2.py"
    spec = importlib.util.spec_from_file_location("migrate_strategy_v1_to_v2", script_path)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _starter(mod: Any) -> dict[str, dict[str, Any]]:
    args = Namespace(
        max_outlier_rate=0.10,
        max_high_risk_rate=0.05,
        max_review_rate=0.20,
        sample_size=200,
        min_group_size=10,
        min_groups=2,
        min_group_hit_rate=0.60,
        max_group_hit_rate_gap=0.25,
        min_coverage=0.90,
        max_near_miss_rate=0.15,
        max_near_miss_count=10,
    )
    return mod.build_starter_policies(args)


def test_promotes_v1_to_v2_with_starter_policies() -> None:
    mod = _load_module()
    payload = {
        "concept_id": "debt_capacity.indebtedness",
        "acceptance_policy_version": "v1",
    }
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policies=_starter(mod),
        force=False,
        concept_ids=set(),
        concept_prefixes=(),
        path=Path("x.json"),
        include_globs=[],
        exclude_globs=[],
    )
    assert changed is True
    assert status == "updated"
    assert updated["acceptance_policy_version"] == "v2"
    assert "outlier_policy" in updated
    assert "template_stability_policy" in updated
    assert "did_not_find_policy" in updated


def test_migrate_normalizes_legacy_template_overrides() -> None:
    mod = _load_module()
    payload = {
        "concept_id": "debt_capacity.indebtedness",
        "acceptance_policy_version": "v1",
        "template_overrides": [
            ["cahill.heading_patterns", "[\"Limitation on Debt\"]"],
            ["kirkland.min_score_margin", "0.05"],
        ],
    }
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policies=_starter(mod),
        force=False,
        concept_ids=set(),
        concept_prefixes=(),
        path=Path("x.json"),
        include_globs=[],
        exclude_globs=[],
    )
    assert changed is True
    assert status == "updated"
    assert updated["template_overrides"]["cahill"]["heading_patterns"] == [
        "Limitation on Debt"
    ]
    assert updated["template_overrides"]["kirkland"]["min_score_margin"] == 0.05


def test_filter_by_concept_prefix() -> None:
    mod = _load_module()
    payload = {
        "concept_id": "liens.permitted_liens",
        "acceptance_policy_version": "v1",
    }
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policies=_starter(mod),
        force=False,
        concept_ids=set(),
        concept_prefixes=("debt_capacity.indebtedness",),
        path=Path("x.json"),
        include_globs=[],
        exclude_globs=[],
    )
    assert changed is False
    assert status == "skip_filtered"
    assert updated["acceptance_policy_version"] == "v1"


def test_skip_already_v2_without_force() -> None:
    mod = _load_module()
    payload = {
        "concept_id": "debt_capacity.indebtedness",
        "acceptance_policy_version": "v2",
        "outlier_policy": {"sample_size": 50},
    }
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policies=_starter(mod),
        force=False,
        concept_ids=set(),
        concept_prefixes=(),
        path=Path("x.json"),
        include_globs=[],
        exclude_globs=[],
    )
    assert changed is False
    assert status == "skip_already_v2"
    assert updated["outlier_policy"]["sample_size"] == 50


def test_force_updates_v2_starter_keys_preserving_non_starter_keys() -> None:
    mod = _load_module()
    payload = {
        "concept_id": "debt_capacity.indebtedness",
        "acceptance_policy_version": "v2",
        "outlier_policy": {"sample_size": 50, "custom": "keep"},
    }
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policies=_starter(mod),
        force=True,
        concept_ids=set(),
        concept_prefixes=(),
        path=Path("x.json"),
        include_globs=[],
        exclude_globs=[],
    )
    assert changed is True
    assert status == "updated"
    assert updated["outlier_policy"]["sample_size"] == 200
    assert updated["outlier_policy"]["custom"] == "keep"


def test_include_exclude_glob_filters() -> None:
    mod = _load_module()
    payload = {
        "concept_id": "debt_capacity.indebtedness",
        "acceptance_policy_version": "v1",
    }
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policies=_starter(mod),
        force=False,
        concept_ids=set(),
        concept_prefixes=(),
        path=Path("workspaces/indebtedness/strategies/debt_capacity.indebtedness_v001.json"),
        include_globs=["*indebtedness_v001.json"],
        exclude_globs=["*current.json"],
    )
    assert changed is True
    assert status == "updated"

    _, changed2, status2 = mod.migrate_strategy_payload(
        payload,
        starter_policies=_starter(mod),
        force=False,
        concept_ids=set(),
        concept_prefixes=(),
        path=Path("workspaces/indebtedness/strategies/current.json"),
        include_globs=["*json"],
        exclude_globs=["*current.json"],
    )
    assert changed2 is False
    assert status2 == "skip_filtered"


def test_migrate_file_dry_run_does_not_write(tmp_path: Path) -> None:
    mod = _load_module()
    strategy_path = tmp_path / "strategy.json"
    strategy_path.write_text(
        json.dumps({"concept_id": "debt_capacity.indebtedness", "acceptance_policy_version": "v1"})
    )
    res = mod.migrate_file(
        strategy_path,
        starter_policies=_starter(mod),
        force=False,
        dry_run=True,
        backup=False,
        concept_ids=set(),
        concept_prefixes=(),
        include_globs=[],
        exclude_globs=[],
    )
    assert res["changed"] is True
    after = json.loads(strategy_path.read_text())
    assert after["acceptance_policy_version"] == "v1"
    assert "did_not_find_policy" not in after


def test_migrate_file_write_and_backup(tmp_path: Path) -> None:
    mod = _load_module()
    strategy_path = tmp_path / "strategy.json"
    strategy_path.write_text(
        json.dumps({"concept_id": "debt_capacity.indebtedness", "acceptance_policy_version": "v1"})
    )
    res = mod.migrate_file(
        strategy_path,
        starter_policies=_starter(mod),
        force=False,
        dry_run=False,
        backup=True,
        concept_ids=set(),
        concept_prefixes=(),
        include_globs=[],
        exclude_globs=[],
    )
    assert res["changed"] is True
    assert "backup" in res
    assert Path(res["backup"]).exists()
    after = json.loads(strategy_path.read_text())
    assert after["acceptance_policy_version"] == "v2"
    assert after["did_not_find_policy"]["min_coverage"] == 0.9
