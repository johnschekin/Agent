"""Run-manifest utilities for corpus build reproducibility and comparison."""
from __future__ import annotations

import importlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.io_utils import load_json, save_json

_duckdb_mod = importlib.import_module("duckdb")

MANIFEST_VERSION = "1.0"
MANIFEST_FILENAME = "run_manifest.json"

DEFAULT_TABLES: tuple[str, ...] = (
    "documents",
    "sections",
    "clauses",
    "definitions",
    "section_text",
)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


def generate_run_id(prefix: str = "corpus_build") -> str:
    """Generate a compact run id suitable for artifact naming."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{ts}_{uuid4().hex[:8]}"


def default_manifest_path_for_db(db_path: Path) -> Path:
    """Return canonical sidecar manifest path for a DuckDB file."""
    return db_path.parent / MANIFEST_FILENAME


def versioned_manifest_path_for_db(db_path: Path, run_id: str) -> Path:
    """Return run-id-specific sidecar manifest path for a DuckDB file."""
    return db_path.parent / f"run_manifest_{run_id}.json"


def git_commit_hash(*, search_from: Path | None = None) -> str | None:
    """Best-effort current git commit hash for reproducibility metadata."""
    cwd = (search_from or Path.cwd())
    if cwd.is_file():
        cwd = cwd.parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out if out else None


def table_row_counts(
    db_path: Path,
    *,
    tables: tuple[str, ...] = DEFAULT_TABLES,
) -> dict[str, int]:
    """Read row counts for expected corpus tables from a DuckDB snapshot."""
    conn = _duckdb_mod.connect(str(db_path), read_only=True)
    try:
        existing = {
            str(r[0]) for r in conn.execute("SHOW TABLES").fetchall()
        }
        counts: dict[str, int] = {}
        for table in tables:
            if table not in existing:
                counts[table] = 0
                continue
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0]) if row else 0
        return counts
    finally:
        conn.close()


def schema_version(db_path: Path) -> str:
    """Read schema version from _schema_version table."""
    conn = _duckdb_mod.connect(str(db_path), read_only=True)
    try:
        row = conn.execute(
            "SELECT version FROM _schema_version WHERE table_name = 'corpus'"
        ).fetchone()
        return str(row[0]) if row else "unknown"
    except Exception:
        return "unknown"
    finally:
        conn.close()


def build_manifest(
    *,
    run_id: str,
    db_path: Path,
    input_source: dict[str, Any],
    timings_sec: dict[str, float],
    errors_count: int,
    stats: dict[str, Any] | None = None,
    git_commit: str | None = None,
    notes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build canonical manifest payload for a corpus snapshot."""
    return {
        "manifest_version": MANIFEST_VERSION,
        "created_at": utc_now_iso(),
        "run_id": run_id,
        "db_path": str(db_path),
        "schema_version": schema_version(db_path),
        "git_commit": git_commit,
        "input_source": input_source,
        "table_row_counts": table_row_counts(db_path),
        "timings_sec": timings_sec,
        "errors_count": int(errors_count),
        "stats": stats or {},
        "notes": notes or {},
    }


def write_manifest(
    db_path: Path,
    manifest: dict[str, Any],
) -> tuple[Path, Path]:
    """Write canonical + versioned manifest files side-by-side with DB."""
    canonical = default_manifest_path_for_db(db_path)
    versioned = versioned_manifest_path_for_db(db_path, str(manifest["run_id"]))
    save_json(manifest, canonical, pretty=True)
    save_json(manifest, versioned, pretty=True)
    return canonical, versioned


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a manifest from JSON."""
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid manifest payload in {path}")
    return data


def compare_manifests(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    """Compare two manifest payloads and produce deterministic deltas."""
    curr_counts = current.get("table_row_counts", {})
    prev_counts = previous.get("table_row_counts", {})
    curr_counts = curr_counts if isinstance(curr_counts, dict) else {}
    prev_counts = prev_counts if isinstance(prev_counts, dict) else {}

    keys = sorted(set(curr_counts.keys()) | set(prev_counts.keys()))
    count_delta: dict[str, int] = {}
    for key in keys:
        curr_val = int(curr_counts.get(key, 0) or 0)
        prev_val = int(prev_counts.get(key, 0) or 0)
        count_delta[key] = curr_val - prev_val

    curr_errors = int(current.get("errors_count", 0) or 0)
    prev_errors = int(previous.get("errors_count", 0) or 0)

    curr_schema = str(current.get("schema_version", "unknown"))
    prev_schema = str(previous.get("schema_version", "unknown"))

    return {
        "current_run_id": current.get("run_id"),
        "previous_run_id": previous.get("run_id"),
        "schema_version_changed": curr_schema != prev_schema,
        "schema_version_current": curr_schema,
        "schema_version_previous": prev_schema,
        "table_row_count_delta": count_delta,
        "errors_count_delta": curr_errors - prev_errors,
    }
