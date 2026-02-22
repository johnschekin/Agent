#!/usr/bin/env python3
"""Persist strategy with versioning + regression circuit breaker.

Usage:
    python3 scripts/strategy_writer.py \\
      --concept-id debt_capacity.indebtedness \\
      --workspace workspaces/indebtedness \\
      --strategy updated.json \\
      --note "Added Cahill heading variant" \\
      --db corpus_index/corpus.duckdb

Outputs structured JSON to stdout, human messages to stderr.
"""

import argparse
import glob
import json
import re
import sys
from pathlib import Path

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def load_json(path: Path) -> object:
        return orjson.loads(path.read_bytes())

    def write_json(path: Path, obj: object) -> None:
        path.write_bytes(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def load_json(path: Path) -> object:
        with open(path) as f:
            return json.load(f)

    def write_json(path: Path, obj: object) -> None:
        with open(path, "w") as f:
            json.dump(obj, f, indent=2, default=str)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def find_latest_version(strategies_dir: Path, concept_id: str) -> tuple[int, Path | None]:
    """Find the latest version number and path for a concept's strategy."""
    pattern = str(strategies_dir / f"{concept_id}_v*.json")
    files = glob.glob(pattern)

    if not files:
        return 0, None

    max_version = 0
    max_path: Path | None = None

    for f in files:
        match = re.search(r"_v(\d+)\.json$", f)
        if match:
            version = int(match.group(1))
            if version > max_version:
                max_version = version
                max_path = Path(f)

    return max_version, max_path


def run_strategy_against_docs(
    strategy: object, con: object, concept_id: str
) -> dict[str, dict]:
    """Run a strategy against all docs and return hit rates grouped by template_family.

    Returns: {group_name: {"hits": int, "total": int, "hit_rate": float}}
    """
    import duckdb

    assert isinstance(con, duckdb.DuckDBPyConnection)

    # Discover tables
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]

    # Find documents table
    docs_table = None
    for candidate in ["documents", "docs", "document", "metadata"]:
        if candidate in tables:
            docs_table = candidate
            break

    if not docs_table:
        log("Warning: no documents table found for regression test")
        return {}

    columns_info = con.execute(
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{docs_table}'"
    ).fetchall()
    columns = [row[0] for row in columns_info]

    doc_id_col = next(
        (c for c in columns if c in ("doc_id", "document_id", "id")), None
    )
    family_col = next(
        (c for c in columns if c in ("template_family", "family", "firm", "law_firm")),
        None,
    )
    text_col = next(
        (c for c in columns if c in ("text", "content", "body", "full_text")), None
    )

    if not doc_id_col:
        log("Warning: no doc_id column found in documents table")
        return {}

    # Get docs with optional grouping
    select_parts = [doc_id_col]
    if family_col:
        select_parts.append(family_col)
    if text_col:
        select_parts.append(text_col)

    rows = con.execute(f"SELECT {', '.join(select_parts)} FROM {docs_table}").fetchall()

    # Extract patterns from strategy
    if not isinstance(strategy, dict):
        log("Warning: strategy is not a dict, cannot run regression")
        return {}

    patterns: list[re.Pattern] = []
    strategy_patterns = strategy.get("patterns", [])
    if isinstance(strategy_patterns, list):
        for p in strategy_patterns:
            if isinstance(p, str):
                try:
                    patterns.append(re.compile(p, re.IGNORECASE))
                except re.error:
                    pass
            elif isinstance(p, dict):
                pat_str = p.get("pattern", p.get("regex", ""))
                if pat_str:
                    try:
                        flags = re.IGNORECASE
                        if p.get("multiline"):
                            flags |= re.MULTILINE
                        patterns.append(re.compile(pat_str, flags))
                    except re.error:
                        pass

    # Also check for heading_patterns, keyword_patterns
    for key in ("heading_patterns", "keyword_patterns", "regexes"):
        extra = strategy.get(key, [])
        if isinstance(extra, list):
            for p in extra:
                pat_str = p if isinstance(p, str) else (p.get("pattern", "") if isinstance(p, dict) else "")
                if pat_str:
                    try:
                        patterns.append(re.compile(pat_str, re.IGNORECASE))
                    except re.error:
                        pass

    if not patterns:
        log("Warning: no valid patterns found in strategy")
        return {}

    # Run patterns against docs
    groups: dict[str, dict] = {}

    for row in rows:
        doc_id = row[0]
        group = row[1] if family_col and len(row) > 1 else "all"
        doc_text = row[2] if text_col and len(row) > 2 else ""

        if group is None:
            group = "unknown"

        if group not in groups:
            groups[group] = {"hits": 0, "total": 0, "hit_rate": 0.0}

        groups[group]["total"] += 1

        if doc_text:
            hit = any(p.search(doc_text) for p in patterns)
            if hit:
                groups[group]["hits"] += 1

    # Calculate hit rates
    for g in groups.values():
        if g["total"] > 0:
            g["hit_rate"] = round(g["hits"] / g["total"], 4)

    return groups


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persist strategy with versioning + regression circuit breaker."
    )
    parser.add_argument("--concept-id", required=True, help="Concept ID")
    parser.add_argument(
        "--workspace", required=True, help="Workspace directory"
    )
    parser.add_argument(
        "--strategy", required=True, help="Path to updated strategy JSON file"
    )
    parser.add_argument("--note", default="", help="Update note")
    parser.add_argument(
        "--db", default=None, help="Corpus DB path (for regression testing)"
    )
    parser.add_argument(
        "--regression-threshold",
        type=float,
        default=0.10,
        help="Max allowed hit rate drop per group (default: 0.10)",
    )
    parser.add_argument(
        "--skip-regression",
        action="store_true",
        help="Skip regression check (for bootstrapping)",
    )
    args = parser.parse_args()

    strategy_path = Path(args.strategy)
    if not strategy_path.exists():
        log(f"Error: strategy file not found at {strategy_path}")
        sys.exit(1)

    workspace = Path(args.workspace)
    strategies_dir = workspace / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)

    # Load updated strategy
    updated_strategy = load_json(strategy_path)
    log(f"Loaded updated strategy from {strategy_path}")

    # Find current version
    current_version, current_path = find_latest_version(strategies_dir, args.concept_id)
    log(f"Current version: {current_version}" + (f" ({current_path})" if current_path else " (none)"))

    # Regression check
    if not args.skip_regression and args.db and current_path:
        db_path = Path(args.db)
        if not db_path.exists():
            log(f"Warning: database not found at {db_path}, skipping regression check")
        else:
            try:
                import duckdb
            except ImportError:
                log("Warning: duckdb not available, skipping regression check")
                duckdb = None

            if duckdb:
                log("Running regression check...")
                con = duckdb.connect(str(db_path), read_only=True)

                current_strategy = load_json(current_path)
                old_results = run_strategy_against_docs(current_strategy, con, args.concept_id)
                new_results = run_strategy_against_docs(updated_strategy, con, args.concept_id)

                con.close()

                regressions: list[dict] = []
                improvements: list[dict] = []

                all_groups = set(old_results.keys()) | set(new_results.keys())
                for group in sorted(all_groups):
                    old_rate = old_results.get(group, {}).get("hit_rate", 0.0)
                    new_rate = new_results.get(group, {}).get("hit_rate", 0.0)
                    delta = round(new_rate - old_rate, 4)

                    if delta < -args.regression_threshold:
                        regressions.append({
                            "group": group,
                            "old_rate": old_rate,
                            "new_rate": new_rate,
                            "delta": delta,
                        })
                    elif delta > 0:
                        improvements.append({
                            "group": group,
                            "old_rate": old_rate,
                            "new_rate": new_rate,
                            "delta": delta,
                        })

                if regressions:
                    log(f"REGRESSION DETECTED: {len(regressions)} group(s) exceeded threshold")
                    dump_json({
                        "status": "rejected",
                        "concept_id": args.concept_id,
                        "reason": "Regression detected",
                        "regressions": regressions,
                        "improvements": improvements,
                    })
                    sys.exit(1)

                log("Regression check passed")
                if improvements:
                    log(f"Improvements in {len(improvements)} group(s)")

    # Save new version
    new_version = current_version + 1
    version_str = f"v{new_version:03d}"
    new_filename = f"{args.concept_id}_{version_str}.json"
    new_path = strategies_dir / new_filename

    # Add metadata to strategy
    if isinstance(updated_strategy, dict):
        updated_strategy["_meta"] = {
            "concept_id": args.concept_id,
            "version": new_version,
            "note": args.note,
            "previous_version": current_version if current_version > 0 else None,
        }

    write_json(new_path, updated_strategy)
    log(f"Wrote strategy to {new_path}")

    # Update current.json symlink (use a regular file copy for portability)
    current_link = strategies_dir / "current.json"
    try:
        if current_link.is_symlink() or current_link.exists():
            current_link.unlink()
        current_link.symlink_to(new_filename)
        log(f"Updated current.json -> {new_filename}")
    except OSError:
        # Fallback: write a redirect file
        write_json(current_link, {"current": new_filename, "version": new_version})
        log(f"Wrote current.json pointer to {new_filename}")

    dump_json({
        "status": "saved",
        "concept_id": args.concept_id,
        "version": new_version,
        "path": str(new_path),
        "note": args.note,
    })


if __name__ == "__main__":
    main()
