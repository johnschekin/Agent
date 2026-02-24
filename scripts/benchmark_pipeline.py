#!/usr/bin/env python3
"""Benchmark pipeline stages for cost/latency budgeting.

Runs standardized benchmark sweeps for sample sizes (default: 100/500/5000)
and emits both JSON and Markdown reports with wall/cpu/docs-per-sec metrics.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import resource
except Exception:  # pragma: no cover - resource may be unavailable on non-Unix
    resource = None  # type: ignore[assignment]

try:
    import orjson

    def _loads(raw: str) -> Any:
        return orjson.loads(raw.encode("utf-8"))

    def _dump_stdout(obj: Any) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def _write_json(path: Path, obj: Any) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except Exception:

    def _loads(raw: str) -> Any:
        return json.loads(raw)

    def _dump_stdout(obj: Any) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def _write_json(path: Path, obj: Any) -> None:
        path.write_text(json.dumps(obj, indent=2, default=str))


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _parse_csv_ints(value: str) -> list[int]:
    out: list[int] = []
    for part in value.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        out.append(max(1, int(stripped)))
    if not out:
        raise ValueError("No sample sizes provided.")
    return out


def _parse_csv_tools(value: str) -> list[str]:
    allowed = {"pattern_tester", "child_locator"}
    out: list[str] = []
    for part in value.split(","):
        tool = part.strip().lower()
        if not tool:
            continue
        if tool not in allowed:
            raise ValueError(f"Unknown tool '{tool}'. Allowed: {sorted(allowed)}")
        out.append(tool)
    if not out:
        raise ValueError("No tools provided.")
    return out


def _run_command(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    before_usage = resource.getrusage(resource.RUSAGE_CHILDREN) if resource else None
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    wall_sec = time.perf_counter() - t0
    after_usage = resource.getrusage(resource.RUSAGE_CHILDREN) if resource else None

    cpu_sec = None
    peak_rss_kb = None
    if before_usage is not None and after_usage is not None:
        cpu_sec = (
            (after_usage.ru_utime - before_usage.ru_utime)
            + (after_usage.ru_stime - before_usage.ru_stime)
        )
        # ru_maxrss is a high-water mark; delta is a rough estimate per command.
        peak_rss_kb = max(0, int(after_usage.ru_maxrss - before_usage.ru_maxrss))

    payload: Any = None
    parse_error: str | None = None
    if proc.stdout.strip():
        try:
            payload = _loads(proc.stdout)
        except Exception as exc:  # noqa: BLE001
            parse_error = f"{type(exc).__name__}: {exc}"

    return {
        "command": cmd,
        "returncode": proc.returncode,
        "wall_time_sec": wall_sec,
        "cpu_time_sec": cpu_sec,
        "peak_rss_kb": peak_rss_kb,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "payload": payload,
        "parse_error": parse_error,
    }


def _count_pattern_tester_docs(payload: Any) -> int:
    if isinstance(payload, dict):
        try:
            return int(payload.get("total_docs", 0) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _load_parent_matches(path: Path) -> list[dict[str, Any]]:
    payload = _loads(path.read_text())
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("matches"), list):
            return [row for row in payload["matches"] if isinstance(row, dict)]
        if isinstance(payload.get("hits"), list):
            return [row for row in payload["hits"] if isinstance(row, dict)]
    return []


def _subset_parent_matches(rows: list[dict[str, Any]], target_docs: int) -> list[dict[str, Any]]:
    keep: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for row in rows:
        doc_id = str(row.get("doc_id", "")).strip()
        if not doc_id:
            continue
        if doc_id not in seen_docs and len(seen_docs) >= target_docs:
            continue
        seen_docs.add(doc_id)
        keep.append(row)
    return keep


def _count_parent_docs(rows: list[dict[str, Any]]) -> int:
    return len({str(row.get("doc_id", "")).strip() for row in rows if str(row.get("doc_id", "")).strip()})


def _summarize_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_tool: dict[str, dict[str, Any]] = {}
    for rec in records:
        tool = str(rec.get("tool", "unknown"))
        tool_bucket = by_tool.setdefault(
            tool,
            {
                "runs": 0,
                "ok_runs": 0,
                "avg_wall_time_sec": 0.0,
                "avg_docs_per_sec": 0.0,
            },
        )
        tool_bucket["runs"] += 1
        if rec.get("status") == "ok":
            tool_bucket["ok_runs"] += 1
            tool_bucket["avg_wall_time_sec"] += float(rec.get("wall_time_sec", 0.0) or 0.0)
            tool_bucket["avg_docs_per_sec"] += float(rec.get("docs_per_sec", 0.0) or 0.0)

    for tool_bucket in by_tool.values():
        ok_runs = int(tool_bucket["ok_runs"])
        if ok_runs > 0:
            tool_bucket["avg_wall_time_sec"] = round(tool_bucket["avg_wall_time_sec"] / ok_runs, 4)
            tool_bucket["avg_docs_per_sec"] = round(tool_bucket["avg_docs_per_sec"] / ok_runs, 4)
        else:
            tool_bucket["avg_wall_time_sec"] = 0.0
            tool_bucket["avg_docs_per_sec"] = 0.0
    return by_tool


def _render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Benchmark Pipeline Report")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- DB: `{report['config']['db']}`")
    lines.append(f"- Sample sizes: `{report['config']['sample_sizes']}`")
    lines.append("")
    lines.append("| Tool | Sample | Status | Docs | Wall(s) | CPU(s) | Docs/s | Mem KB |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|")
    for rec in report.get("results", []):
        lines.append(
            "| {tool} | {sample} | {status} | {docs} | {wall:.4f} | {cpu} | {dps:.4f} | {mem} |".format(
                tool=rec.get("tool", ""),
                sample=rec.get("sample_size", 0),
                status=rec.get("status", ""),
                docs=rec.get("evaluated_docs", 0),
                wall=float(rec.get("wall_time_sec", 0.0) or 0.0),
                cpu=(
                    f"{float(rec['cpu_time_sec']):.4f}"
                    if rec.get("cpu_time_sec") is not None
                    else "n/a"
                ),
                dps=float(rec.get("docs_per_sec", 0.0) or 0.0),
                mem=rec.get("memory_estimate_kb", "n/a"),
            )
        )

    lines.append("")
    lines.append("## Summary")
    for tool, summary in report.get("summary", {}).items():
        lines.append(
            f"- `{tool}`: ok {summary['ok_runs']}/{summary['runs']}, "
            f"avg wall `{summary['avg_wall_time_sec']}`s, "
            f"avg docs/s `{summary['avg_docs_per_sec']}`"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Agent pipeline tools.")
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument("--strategy", required=True, help="Path to strategy JSON for pattern_tester.")
    parser.add_argument(
        "--tools",
        default="pattern_tester,child_locator",
        help="Comma-separated tools to benchmark: pattern_tester,child_locator",
    )
    parser.add_argument(
        "--sample-sizes",
        default="100,500,5000",
        help="Comma-separated sample sizes (default: 100,500,5000).",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    parser.add_argument(
        "--child-parent-matches",
        default=None,
        help="Optional parent matches JSON input for child_locator benchmarking.",
    )
    parser.add_argument(
        "--child-keywords",
        default=None,
        help="Comma-separated child keywords for child_locator.",
    )
    parser.add_argument(
        "--child-headings",
        default=None,
        help="Comma-separated child heading patterns for child_locator.",
    )
    parser.add_argument(
        "--output-json",
        default="corpus_index/benchmark_pipeline.json",
        help="Output benchmark JSON path.",
    )
    parser.add_argument(
        "--output-md",
        default=None,
        help="Optional output markdown path. Default: output_json with .md suffix.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    db_path = Path(args.db).resolve()
    strategy_path = Path(args.strategy).resolve()
    sample_sizes = _parse_csv_ints(args.sample_sizes)
    tools = _parse_csv_tools(args.tools)
    output_json_path = Path(args.output_json).resolve()
    output_md_path = (
        Path(args.output_md).resolve()
        if args.output_md
        else output_json_path.with_suffix(".md")
    )
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    python = sys.executable

    child_parent_rows: list[dict[str, Any]] = []
    if "child_locator" in tools and args.child_parent_matches:
        child_parent_rows = _load_parent_matches(Path(args.child_parent_matches).resolve())
        _log(f"Loaded {len(child_parent_rows)} parent matches for child_locator benchmark.")

    records: list[dict[str, Any]] = []

    for sample_size in sample_sizes:
        if "pattern_tester" in tools:
            cmd = [
                python,
                str(root / "scripts" / "pattern_tester.py"),
                "--db",
                str(db_path),
                "--strategy",
                str(strategy_path),
                "--sample",
                str(sample_size),
            ]
            if args.include_all:
                cmd.append("--include-all")
            _log(f"Benchmark: pattern_tester sample={sample_size}")
            run = _run_command(cmd, cwd=root, env=env)
            evaluated_docs = _count_pattern_tester_docs(run["payload"])
            wall = float(run["wall_time_sec"] or 0.0)
            records.append(
                {
                    "tool": "pattern_tester",
                    "sample_size": sample_size,
                    "status": (
                        "ok"
                        if run["returncode"] == 0 and run["parse_error"] is None
                        else "error"
                    ),
                    "evaluated_docs": evaluated_docs,
                    "wall_time_sec": round(wall, 6),
                    "cpu_time_sec": (
                        round(float(run["cpu_time_sec"]), 6)
                        if run["cpu_time_sec"] is not None
                        else None
                    ),
                    "docs_per_sec": round(evaluated_docs / wall, 6) if wall > 0 else 0.0,
                    "memory_estimate_kb": run["peak_rss_kb"],
                    "returncode": run["returncode"],
                    "parse_error": run["parse_error"],
                    "stderr_tail": run["stderr"][-1000:],
                }
            )

        if "child_locator" in tools:
            if not child_parent_rows:
                records.append(
                    {
                        "tool": "child_locator",
                        "sample_size": sample_size,
                        "status": "skipped",
                        "reason": "missing --child-parent-matches",
                        "evaluated_docs": 0,
                        "wall_time_sec": 0.0,
                        "cpu_time_sec": None,
                        "docs_per_sec": 0.0,
                        "memory_estimate_kb": None,
                    }
                )
                continue

            subset_rows = _subset_parent_matches(child_parent_rows, sample_size)
            subset_docs = _count_parent_docs(subset_rows)
            if subset_docs == 0:
                records.append(
                    {
                        "tool": "child_locator",
                        "sample_size": sample_size,
                        "status": "skipped",
                        "reason": "no parent matches for requested sample",
                        "evaluated_docs": 0,
                        "wall_time_sec": 0.0,
                        "cpu_time_sec": None,
                        "docs_per_sec": 0.0,
                        "memory_estimate_kb": None,
                    }
                )
                continue

            with tempfile.TemporaryDirectory(prefix="bench_child_") as tmpdir:
                parent_subset_path = Path(tmpdir) / "parent_subset.json"
                parent_subset_path.write_text(json.dumps(subset_rows, indent=2))
                cmd = [
                    python,
                    str(root / "scripts" / "child_locator.py"),
                    "--db",
                    str(db_path),
                    "--parent-matches",
                    str(parent_subset_path),
                ]
                if args.child_keywords:
                    cmd.extend(["--child-keywords", args.child_keywords])
                if args.child_headings:
                    cmd.extend(["--child-headings", args.child_headings])
                if args.include_all:
                    cmd.append("--include-all")

                _log(f"Benchmark: child_locator sample={sample_size} (docs={subset_docs})")
                run = _run_command(cmd, cwd=root, env=env)
                wall = float(run["wall_time_sec"] or 0.0)
                match_count = len(run["payload"]) if isinstance(run["payload"], list) else 0
                records.append(
                    {
                        "tool": "child_locator",
                        "sample_size": sample_size,
                        "status": (
                            "ok"
                            if run["returncode"] == 0 and run["parse_error"] is None
                            else "error"
                        ),
                        "evaluated_docs": subset_docs,
                        "match_count": match_count,
                        "wall_time_sec": round(wall, 6),
                        "cpu_time_sec": (
                            round(float(run["cpu_time_sec"]), 6)
                            if run["cpu_time_sec"] is not None
                            else None
                        ),
                        "docs_per_sec": round(subset_docs / wall, 6) if wall > 0 else 0.0,
                        "memory_estimate_kb": run["peak_rss_kb"],
                        "returncode": run["returncode"],
                        "parse_error": run["parse_error"],
                        "stderr_tail": run["stderr"][-1000:],
                    }
                )

    report: dict[str, Any] = {
        "schema_version": "benchmark_pipeline_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "db": str(db_path),
            "strategy": str(strategy_path),
            "tools": tools,
            "sample_sizes": sample_sizes,
            "include_all": bool(args.include_all),
            "child_parent_matches": args.child_parent_matches,
        },
        "results": records,
        "summary": _summarize_results(records),
    }

    _write_json(output_json_path, report)
    output_md_path.write_text(_render_markdown(report))
    _dump_stdout(
        {
            "status": "ok",
            "output_json": str(output_json_path),
            "output_md": str(output_md_path),
            "runs": len(records),
        }
    )


if __name__ == "__main__":
    main()
