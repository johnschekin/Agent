"""Tests for migrate_v2_did_not_find_policy utility."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_module() -> Any:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "migrate_v2_did_not_find_policy.py"
    spec = importlib.util.spec_from_file_location("migrate_v2_did_not_find_policy", script_path)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_migrate_payload_skips_non_v2() -> None:
    mod = _load_module()
    starter = mod.build_starter_policy(
        min_coverage=0.9,
        max_near_miss_rate=0.15,
        max_near_miss_count=10,
    )
    payload = {"acceptance_policy_version": "v1"}
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policy=starter,
        force=False,
    )
    assert changed is False
    assert status == "skip_not_v2"
    assert updated["acceptance_policy_version"] == "v1"


def test_migrate_payload_adds_missing_policy() -> None:
    mod = _load_module()
    starter = mod.build_starter_policy(
        min_coverage=0.9,
        max_near_miss_rate=0.15,
        max_near_miss_count=10,
    )
    payload = {"acceptance_policy_version": "v2"}
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policy=starter,
        force=False,
    )
    assert changed is True
    assert status == "updated"
    assert updated["did_not_find_policy"]["min_coverage"] == 0.9
    assert updated["did_not_find_policy"]["max_near_miss_rate"] == 0.15
    assert updated["did_not_find_policy"]["max_near_miss_count"] == 10


def test_migrate_payload_preserves_existing_values_without_force() -> None:
    mod = _load_module()
    starter = mod.build_starter_policy(
        min_coverage=0.9,
        max_near_miss_rate=0.15,
        max_near_miss_count=10,
    )
    payload = {
        "acceptance_policy_version": "v2",
        "did_not_find_policy": {"min_coverage": 0.8},
    }
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policy=starter,
        force=False,
    )
    assert changed is True
    assert status == "updated"
    assert updated["did_not_find_policy"]["min_coverage"] == 0.8
    assert updated["did_not_find_policy"]["max_near_miss_rate"] == 0.15
    assert updated["did_not_find_policy"]["max_near_miss_count"] == 10


def test_migrate_payload_force_overrides_starter_keys() -> None:
    mod = _load_module()
    starter = mod.build_starter_policy(
        min_coverage=0.9,
        max_near_miss_rate=0.15,
        max_near_miss_count=10,
    )
    payload = {
        "acceptance_policy_version": "v2",
        "did_not_find_policy": {"min_coverage": 0.8, "extra": "keep"},
    }
    updated, changed, status = mod.migrate_strategy_payload(
        payload,
        starter_policy=starter,
        force=True,
    )
    assert changed is True
    assert status == "updated"
    assert updated["did_not_find_policy"]["min_coverage"] == 0.9
    assert updated["did_not_find_policy"]["max_near_miss_rate"] == 0.15
    assert updated["did_not_find_policy"]["max_near_miss_count"] == 10
    assert updated["did_not_find_policy"]["extra"] == "keep"


def test_migrate_file_dry_run_does_not_write(tmp_path: Path) -> None:
    mod = _load_module()
    strategy_path = tmp_path / "strategy.json"
    strategy_path.write_text(json.dumps({"acceptance_policy_version": "v2"}))
    starter = mod.build_starter_policy(
        min_coverage=0.9,
        max_near_miss_rate=0.15,
        max_near_miss_count=10,
    )

    res = mod.migrate_file(
        strategy_path,
        starter_policy=starter,
        force=False,
        dry_run=True,
        backup=False,
    )
    assert res["changed"] is True
    payload_after = json.loads(strategy_path.read_text())
    assert "did_not_find_policy" not in payload_after


def test_migrate_file_writes_and_backup(tmp_path: Path) -> None:
    mod = _load_module()
    strategy_path = tmp_path / "strategy.json"
    strategy_path.write_text(
        json.dumps(
            {
                "acceptance_policy_version": "v2",
                "did_not_find_policy": {},
            }
        )
    )
    starter = mod.build_starter_policy(
        min_coverage=0.9,
        max_near_miss_rate=0.15,
        max_near_miss_count=10,
        near_miss_cutoff=0.24,
    )

    res = mod.migrate_file(
        strategy_path,
        starter_policy=starter,
        force=False,
        dry_run=False,
        backup=True,
    )
    assert res["changed"] is True
    assert "backup" in res
    backup_path = Path(res["backup"])
    assert backup_path.exists()

    payload_after = json.loads(strategy_path.read_text())
    assert payload_after["did_not_find_policy"]["min_coverage"] == 0.9
    assert payload_after["did_not_find_policy"]["near_miss_cutoff"] == 0.24

