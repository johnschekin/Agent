#!/usr/bin/env python3
"""Run parser_v1 vs parser_v2 dual-run and emit summary report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.parser_v2.dual_run import run_dual_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Parser v2 dual-run shadow evaluator")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=ROOT / "data" / "fixtures" / "gold" / "v1" / "gates" / "replay_smoke_v1.jsonl",
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--sidecar-out",
        type=Path,
        default=ROOT / "artifacts" / "parser_v2_dual_run_sidecar.jsonl",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=ROOT / "artifacts" / "parser_v2_dual_run_report.json",
    )
    parser.add_argument("--overwrite-sidecar", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_dual_run(
        args.fixtures,
        limit=args.limit,
        sidecar_out=args.sidecar_out,
        overwrite_sidecar=args.overwrite_sidecar,
    )

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            json.dumps(
                {
                    "processed_sections": report.get("processed_sections", 0),
                    "section_status_counts": report.get("section_status_counts", {}),
                    "avg_id_overlap_ratio": report.get("avg_id_overlap_ratio", 0.0),
                    "sidecar_path": report.get("sidecar_path"),
                    "report_out": str(args.report_out),
                },
                indent=2,
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
