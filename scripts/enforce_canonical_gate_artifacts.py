#!/usr/bin/env python3
"""Enforce canonical gate artifact routing for a run manifest.

If a run manifest marks workspace state as dirty, gate-critical output pointers
must route to canonical clean-source artifacts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _check_path_exists(path_str: str) -> bool:
    return Path(path_str).exists()


def _is_canonical_path(path_str: str) -> bool:
    return "/canonical/" in path_str


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce canonical gate artifact routing.")
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to day run manifest JSON.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON report.",
    )
    args = parser.parse_args()

    manifest = _load_json(args.manifest)
    git = dict(manifest.get("git") or {})
    dirty = bool(git.get("is_dirty"))
    outputs = dict(manifest.get("output_artifacts") or {})
    closure = dict(manifest.get("provenance_closure") or {})

    required_primary_keys = (
        "validate_report",
        "replay_report",
        "clause_guardrail_report",
        "parent_guardrail_report",
        "parser_v1_tests_log",
    )

    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    for key in required_primary_keys:
        value = str(outputs.get(key) or "")
        exists = _check_path_exists(value) if value else False
        canonical_ok = _is_canonical_path(value) if value else False
        passed = exists and (canonical_ok if dirty else True)
        checks.append(
            {
                "check": f"primary_output::{key}",
                "path": value,
                "exists": exists,
                "canonical_path_required": dirty,
                "canonical_path_ok": canonical_ok,
                "passed": passed,
            },
        )
        if not passed:
            failures.append(f"{key} must exist and route to canonical output when dirty")

    diagnostic_dirty_key = "dirty_replay_report_diagnostic_only"
    dirty_value = str(outputs.get(diagnostic_dirty_key) or "")
    if dirty:
        dirty_exists = _check_path_exists(dirty_value) if dirty_value else False
        dirty_passed = bool(dirty_value) and dirty_exists and ("/canonical/" not in dirty_value)
        checks.append(
            {
                "check": f"diagnostic_output::{diagnostic_dirty_key}",
                "path": dirty_value,
                "exists": dirty_exists,
                "passed": dirty_passed,
            },
        )
        if not dirty_passed:
            failures.append("dirty replay diagnostic pointer missing or invalid")

    policy_path = str(outputs.get("canonical_selection_policy") or "")
    policy_exists = _check_path_exists(policy_path) if policy_path else False
    checks.append(
        {
            "check": "canonical_policy_present",
            "path": policy_path,
            "exists": policy_exists,
            "passed": policy_exists,
        },
    )
    if not policy_exists:
        failures.append("canonical selection policy path missing")

    closure_ok = closure.get("status") == "closed_with_canonical_routing"
    checks.append(
        {
            "check": "provenance_closure_status",
            "status": closure.get("status"),
            "passed": closure_ok,
        },
    )
    if not closure_ok:
        failures.append("provenance_closure.status must be closed_with_canonical_routing")

    report = {
        "schema_version": "canonical-enforcement-report-v1",
        "manifest_path": str(args.manifest),
        "workspace_dirty": dirty,
        "status": "pass" if not failures else "fail",
        "checks": checks,
        "failures": failures,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"canonical enforcement status: {report['status']}")
        for row in checks:
            mark = "PASS" if row.get("passed") else "FAIL"
            print(f"[{mark}] {row.get('check')}")
        if failures:
            print("failures:")
            for msg in failures:
                print(f"- {msg}")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
