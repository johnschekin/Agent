#!/usr/bin/env python3
"""CI gate for clause parsing quality checks.

Runs parser-focused test suites against the repository-local `src/` tree and
writes a machine-readable report for CI artifacting.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "parsing_ci_gate_thresholds.json"


@dataclass(slots=True)
class CheckResult:
    name: str
    command: list[str]
    returncode: int
    duration_s: float
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0



def _run(cmd: list[str], env: dict[str, str]) -> CheckResult:
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return CheckResult(
        name=" ".join(cmd),
        command=cmd,
        returncode=proc.returncode,
        duration_s=round(time.time() - started, 3),
        stdout=proc.stdout,
        stderr=proc.stderr,
    )



def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config: {path}")
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("Config must be a JSON object")
    return payload



def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(ROOT / "src")
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_path if not current else f"{src_path}:{current}"
    return env



def run_gate(mode: str, config_path: Path, skip_compile: bool) -> dict[str, Any]:
    config = _load_config(config_path)
    mode_cfg = config.get(mode)
    if not isinstance(mode_cfg, dict):
        raise ValueError(f"Mode {mode!r} not found in {config_path}")

    env = _build_env()
    checks: list[CheckResult] = []

    pytest_targets = mode_cfg.get("pytest_targets") or []
    if not isinstance(pytest_targets, list) or not pytest_targets:
        raise ValueError(f"Mode {mode!r} missing pytest_targets")

    checks.append(_run(["pytest", "-q", *pytest_targets, "-p", "no:cacheprovider"], env))

    compile_targets = mode_cfg.get("py_compile_targets") or []
    if mode == "full" and not skip_compile and compile_targets:
        for target in compile_targets:
            checks.append(_run(["python3", "-m", "py_compile", str(target)], env))

    all_ok = all(check.ok for check in checks)
    return {
        "ok": all_ok,
        "mode": mode,
        "config": str(config_path),
        "checks": [
            {
                "name": check.name,
                "command": check.command,
                "ok": check.ok,
                "returncode": check.returncode,
                "duration_s": check.duration_s,
                "stdout": check.stdout,
                "stderr": check.stderr,
            }
            for check in checks
        ],
    }



def main() -> int:
    parser = argparse.ArgumentParser(description="Run parser quality CI gate")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--report", default="")
    parser.add_argument("--skip-compile", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else None
    payload = run_gate(args.mode, Path(args.config), args.skip_compile)

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2) + "\n")

    summary = {
        "ok": payload["ok"],
        "mode": payload["mode"],
        "checks": [
            {
                "name": check["name"],
                "ok": check["ok"],
                "duration_s": check["duration_s"],
            }
            for check in payload["checks"]
        ],
    }
    print(json.dumps(summary, indent=2))

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
