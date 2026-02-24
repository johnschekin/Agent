#!/usr/bin/env python3
"""Build a DuckDB corpus index from S3-hosted HTML documents using Ray.

V3: Parquet-sharded architecture + early-exit classification.

Workers return results to the driver, the driver writes Parquet shards in
batches, and a final merge step bulk-loads all shards into DuckDB using
read_parquet() with glob patterns.

Early-exit: non-cohort documents are classified in ~200ms and skip the
expensive section/clause/definition NLP pipeline (~1s). Since ~75% of S3
docs are non-CAs, this cuts total processing time by ~60%.

Default S3 prefixes point to the **trimmed corpus** (3,298 docs, one per
CIK, amendments excluded):
    - ``documents-trimmed/``  — 3,298 HTML credit agreements
    - ``metadata-trimmed/``   — 3,298 .meta.json sidecars

Use ``--doc-prefix documents --meta-prefix metadata`` to process the full
34K corpus instead.

Usage (single instance):
    python3 scripts/build_corpus_ray_v2.py \\
        --bucket edgar-pipeline-documents-216213517387 \\
        --output corpus_index/corpus.duckdb \\
        --local --force -v

Usage (cluster via ray exec):
    ray exec ray-cluster.yaml \\
        '/home/ubuntu/venv/bin/python3 /home/ubuntu/agent/scripts/build_corpus_ray_v2.py \\
        --bucket edgar-pipeline-documents-216213517387 \\
        --output /home/ubuntu/corpus_index/corpus.duckdb \\
        --s3-upload s3://edgar-pipeline-documents-216213517387/corpus_index/corpus-trimmed.duckdb \\
        --force -v'
"""
from __future__ import annotations

import argparse
import importlib
import logging
import shutil
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ray

# ---------------------------------------------------------------------------
# Agent library imports
# ---------------------------------------------------------------------------
from agent.document_processor import (
    ACCESSION_RE,
    SidecarMetadata,
    dedup_by_cik,
    process_document_text,
)
from agent.run_manifest import (
    build_manifest,
    generate_run_id,
    git_commit_hash,
    write_manifest,
)

# Dynamic imports for non-type-checked deps
_duckdb = importlib.import_module("duckdb")

try:
    import orjson

    def _dump_json(obj: object) -> bytes:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2)

    def _load_json(data: bytes) -> Any:
        return orjson.loads(data)
except ImportError:
    import json as _json

    def _dump_json(obj: object) -> bytes:  # type: ignore[misc]
        return _json.dumps(obj, indent=2, default=str).encode("utf-8")

    def _load_json(data: bytes) -> Any:  # type: ignore[misc]
        return _json.loads(data)

log = logging.getLogger("build_corpus_ray_v2")

# ---------------------------------------------------------------------------
# DuckDB Schema DDL (for final merge step)
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS _schema_version (
    table_name VARCHAR PRIMARY KEY,
    version VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT current_timestamp
);

INSERT OR IGNORE INTO _schema_version VALUES ('corpus', '0.2.0', current_timestamp);

CREATE TABLE IF NOT EXISTS documents (
    doc_id VARCHAR PRIMARY KEY,
    cik VARCHAR,
    accession VARCHAR,
    path VARCHAR,
    borrower VARCHAR DEFAULT '',
    admin_agent VARCHAR DEFAULT '',
    facility_size_mm DOUBLE,
    facility_confidence VARCHAR DEFAULT 'none',
    closing_ebitda_mm DOUBLE,
    ebitda_confidence VARCHAR DEFAULT 'none',
    closing_date DATE,
    filing_date DATE,
    form_type VARCHAR DEFAULT '',
    template_family VARCHAR DEFAULT '',
    doc_type VARCHAR DEFAULT 'other',
    doc_type_confidence VARCHAR DEFAULT 'low',
    market_segment VARCHAR DEFAULT 'uncertain',
    segment_confidence VARCHAR DEFAULT 'low',
    cohort_included BOOLEAN DEFAULT false,
    word_count INTEGER DEFAULT 0,
    section_count INTEGER DEFAULT 0,
    clause_count INTEGER DEFAULT 0,
    definition_count INTEGER DEFAULT 0,
    text_length INTEGER DEFAULT 0,
    section_parser_mode VARCHAR DEFAULT '',
    section_fallback_used BOOLEAN DEFAULT false
);

CREATE TABLE IF NOT EXISTS sections (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    heading VARCHAR,
    char_start INTEGER,
    char_end INTEGER,
    article_num INTEGER,
    word_count INTEGER,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE IF NOT EXISTS clauses (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    clause_id VARCHAR NOT NULL,
    label VARCHAR,
    depth INTEGER,
    level_type VARCHAR,
    span_start INTEGER,
    span_end INTEGER,
    header_text VARCHAR,
    clause_text VARCHAR,
    parent_id VARCHAR DEFAULT '',
    is_structural BOOLEAN DEFAULT true,
    parse_confidence DOUBLE DEFAULT 0.0,
    PRIMARY KEY (doc_id, section_number, clause_id)
);

CREATE TABLE IF NOT EXISTS definitions (
    doc_id VARCHAR NOT NULL,
    term VARCHAR NOT NULL,
    definition_text VARCHAR,
    char_start INTEGER,
    char_end INTEGER,
    pattern_engine VARCHAR,
    confidence DOUBLE DEFAULT 0.0,
    definition_type VARCHAR DEFAULT 'DIRECT',
    definition_types VARCHAR,
    type_confidence DOUBLE DEFAULT 0.0,
    type_signals VARCHAR,
    dependency_terms VARCHAR
);

CREATE TABLE IF NOT EXISTS section_text (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    text VARCHAR,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE IF NOT EXISTS section_features (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    article_num INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    word_count INTEGER,
    char_count INTEGER,
    heading_lower VARCHAR,
    scope_label VARCHAR,
    scope_operator_count INTEGER,
    scope_permit_count INTEGER,
    scope_restrict_count INTEGER,
    scope_estimated_depth INTEGER,
    preemption_override_count INTEGER,
    preemption_yield_count INTEGER,
    preemption_estimated_depth INTEGER,
    preemption_has BOOLEAN,
    preemption_edge_count INTEGER,
    definition_types VARCHAR,
    definition_type_primary VARCHAR,
    definition_type_confidence DOUBLE,
    PRIMARY KEY (doc_id, section_number)
);

CREATE TABLE IF NOT EXISTS clause_features (
    doc_id VARCHAR NOT NULL,
    section_number VARCHAR NOT NULL,
    clause_id VARCHAR NOT NULL,
    depth INTEGER,
    level_type VARCHAR,
    token_count INTEGER,
    char_count INTEGER,
    has_digits BOOLEAN,
    parse_confidence DOUBLE,
    is_structural BOOLEAN,
    PRIMARY KEY (doc_id, section_number, clause_id)
);
"""

_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "documents": (
        "doc_id",
        "cik",
        "accession",
        "path",
        "borrower",
        "admin_agent",
        "facility_size_mm",
        "facility_confidence",
        "closing_ebitda_mm",
        "ebitda_confidence",
        "closing_date",
        "filing_date",
        "form_type",
        "template_family",
        "doc_type",
        "doc_type_confidence",
        "market_segment",
        "segment_confidence",
        "cohort_included",
        "word_count",
        "section_count",
        "clause_count",
        "definition_count",
        "text_length",
        "section_parser_mode",
        "section_fallback_used",
    ),
    "sections": (
        "doc_id",
        "section_number",
        "heading",
        "char_start",
        "char_end",
        "article_num",
        "word_count",
    ),
    "clauses": (
        "doc_id",
        "section_number",
        "clause_id",
        "label",
        "depth",
        "level_type",
        "span_start",
        "span_end",
        "header_text",
        "clause_text",
        "parent_id",
        "is_structural",
        "parse_confidence",
    ),
    "definitions": (
        "doc_id",
        "term",
        "definition_text",
        "char_start",
        "char_end",
        "pattern_engine",
        "confidence",
        "definition_type",
        "definition_types",
        "type_confidence",
        "type_signals",
        "dependency_terms",
    ),
    "section_text": (
        "doc_id",
        "section_number",
        "text",
    ),
    "section_features": (
        "doc_id",
        "section_number",
        "article_num",
        "char_start",
        "char_end",
        "word_count",
        "char_count",
        "heading_lower",
        "scope_label",
        "scope_operator_count",
        "scope_permit_count",
        "scope_restrict_count",
        "scope_estimated_depth",
        "preemption_override_count",
        "preemption_yield_count",
        "preemption_estimated_depth",
        "preemption_has",
        "preemption_edge_count",
        "definition_types",
        "definition_type_primary",
        "definition_type_confidence",
    ),
    "clause_features": (
        "doc_id",
        "section_number",
        "clause_id",
        "depth",
        "level_type",
        "token_count",
        "char_count",
        "has_digits",
        "parse_confidence",
        "is_structural",
    ),
}

_TABLE_MERGE_CONFIG: tuple[tuple[str, bool, tuple[str, ...]], ...] = (
    ("documents", True, ("doc_id",)),
    ("sections", True, ("doc_id", "section_number")),
    ("clauses", True, ("doc_id", "section_number", "clause_id")),
    (
        "definitions",
        True,
        ("doc_id", "term", "char_start", "char_end", "definition_text"),
    ),
    ("section_text", True, ("doc_id", "section_number")),
    ("section_features", True, ("doc_id", "section_number")),
    ("clause_features", True, ("doc_id", "section_number", "clause_id")),
)

# ---------------------------------------------------------------------------
# Note: Regex helpers, extract_cik, extract_accession, normalize_date_value,
# compute_doc_id are now in agent.document_processor (imported above).
# ---------------------------------------------------------------------------


def _meta_key_for_doc_key(
    doc_key: str,
    doc_prefix: str = "documents-trimmed",
    meta_prefix: str = "metadata-trimmed",
) -> str | None:
    """Map a document S3 key to its metadata sidecar key."""
    prefix_with_slash = doc_prefix.rstrip("/") + "/"
    if not doc_key.startswith(prefix_with_slash):
        return None
    meta_key = doc_key.replace(prefix_with_slash, meta_prefix.rstrip("/") + "/", 1)
    stem = Path(meta_key).stem
    acc_match = ACCESSION_RE.search(stem)
    if acc_match:
        accession = acc_match.group(1)
        return str(Path(meta_key).with_name(f"{accession}.meta.json"))
    return str(Path(meta_key).with_suffix(".meta.json"))


# ---------------------------------------------------------------------------
# S3 key listing (same as v1)
# ---------------------------------------------------------------------------


def _list_document_keys(
    bucket: str,
    region: str,
    profile: str | None = None,
    doc_prefix: str = "documents-trimmed",
    meta_prefix: str = "metadata-trimmed",
) -> list[tuple[str, str | None]]:
    import boto3

    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    html_extensions = {".htm", ".html"}
    doc_keys: list[str] = []
    s3_prefix = doc_prefix.rstrip("/") + "/"

    log.info("Listing S3 keys in s3://%s/%s ...", bucket, s3_prefix)
    for page in paginator.paginate(Bucket=bucket, Prefix=s3_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if Path(key).suffix.lower() in html_extensions:
                doc_keys.append(key)

    doc_keys.sort()
    log.info("Found %d document keys in S3", len(doc_keys))

    pairs: list[tuple[str, str | None]] = []
    for dk in doc_keys:
        mk = _meta_key_for_doc_key(dk, doc_prefix, meta_prefix)
        pairs.append((dk, mk))

    return pairs


# ---------------------------------------------------------------------------
# Checkpoint manager (same as v1)
# ---------------------------------------------------------------------------


class _CheckpointManager:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._processed: set[str] = set()
        self._errors: list[str] = []
        self._started_at: str = ""
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = _load_json(self._path.read_bytes())
            self._processed = set(data.get("processed_doc_keys", []))
            self._errors = list(data.get("errors", []))
            self._started_at = data.get("started_at", "")
            log.info(
                "Loaded checkpoint: %d processed, %d errors",
                len(self._processed),
                len(self._errors),
            )
        except Exception as exc:
            log.warning("Failed to load checkpoint %s: %s", self._path, exc)

    def is_processed(self, doc_key: str) -> bool:
        return doc_key in self._processed

    def mark_processed(self, doc_keys: list[str]) -> None:
        self._processed.update(doc_keys)

    def mark_error(self, doc_key: str) -> None:
        self._errors.append(doc_key)

    def save(self) -> None:
        if not self._started_at:
            self._started_at = datetime.now(UTC).isoformat()
        data = {
            "processed_doc_keys": sorted(self._processed),
            "errors": self._errors,
            "started_at": self._started_at,
            "last_updated": datetime.now(UTC).isoformat(),
            "total_processed": len(self._processed),
            "total_errors": len(self._errors),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(_dump_json(data))

    @property
    def processed_count(self) -> int:
        return len(self._processed)

    @property
    def error_count(self) -> int:
        return len(self._errors)


# ---------------------------------------------------------------------------
# Remote document processor (v3: early-exit for non-cohort docs)
# ---------------------------------------------------------------------------


@ray.remote(num_cpus=1, max_retries=2)
def process_document(
    bucket: str,
    doc_key: str,
    meta_key: str | None,
    region: str,
) -> dict[str, Any] | None:
    """Process a single S3-hosted HTML document through the agent NLP pipeline.

    Thin wrapper around :func:`agent.document_processor.process_document_text`
    that handles S3 I/O and sidecar loading.

    Creates a fresh boto3 client per invocation (not serializable across Ray).
    Returns a result dict or None on failure.
    """
    import boto3

    try:
        s3 = boto3.client("s3", region_name=region)

        # Step 1: Download HTML from S3
        resp = s3.get_object(Bucket=bucket, Key=doc_key)
        html_bytes = resp["Body"].read()

        try:
            html = html_bytes.decode("utf-8")
        except UnicodeDecodeError:
            html = html_bytes.decode("latin-1")

        if not html or len(html) < 50:
            return None

        # Step 2: Load sidecar metadata from S3
        sidecar: SidecarMetadata | None = None
        if meta_key:
            try:
                meta_resp = s3.get_object(Bucket=bucket, Key=meta_key)
                meta_bytes = meta_resp["Body"].read()
                meta_obj = _load_json(meta_bytes)
                if isinstance(meta_obj, dict):
                    sidecar = SidecarMetadata(
                        company_name=str(meta_obj.get("company_name", "")),
                        cik=str(meta_obj.get("cik", "")),
                        accession=str(meta_obj.get("accession", "")),
                    )
            except Exception:
                pass

        # Step 3: Delegate to shared NLP pipeline
        result = process_document_text(
            html=html,
            path_or_key=doc_key,
            filename=Path(doc_key).name,
            sidecar=sidecar,
            cohort_only_nlp=True,
        )
        if result is None:
            return None

        d = result.to_dict()
        d["doc_key"] = doc_key
        return d

    except Exception as exc:
        print(
            f"  ERROR processing {doc_key}: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Parquet shard writer (NEW in v2)
# ---------------------------------------------------------------------------


def _write_parquet_batch(
    batch: list[dict[str, Any]],
    shard_dir: Path,
    shard_id: int,
) -> dict[str, int]:
    """Write a batch of document results as Parquet shard files.

    Writes 5 files per shard (one per table). PyArrow writes are ~50ms for
    100 documents — negligible compared to the 2-3s DuckDB executemany took.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    all_docs: list[dict[str, Any]] = []
    all_sections: list[dict[str, Any]] = []
    all_clauses: list[dict[str, Any]] = []
    all_definitions: list[dict[str, Any]] = []
    all_section_texts: list[dict[str, Any]] = []
    all_section_features: list[dict[str, Any]] = []
    all_clause_features: list[dict[str, Any]] = []

    for result in batch:
        all_docs.append(result["doc"])
        all_sections.extend(result["sections"])
        all_clauses.extend(result["clauses"])
        all_definitions.extend(result["definitions"])
        all_section_texts.extend(result["section_texts"])
        all_section_features.extend(result.get("section_features", []))
        all_clause_features.extend(result.get("clause_features", []))

    prefix = f"{shard_id:05d}"

    if all_docs:
        table = pa.Table.from_pylist(all_docs)
        pq.write_table(
            table,
            shard_dir / f"documents_{prefix}.parquet",
            compression="zstd",
        )
    if all_sections:
        table = pa.Table.from_pylist(all_sections)
        pq.write_table(
            table,
            shard_dir / f"sections_{prefix}.parquet",
            compression="zstd",
        )
    if all_clauses:
        table = pa.Table.from_pylist(all_clauses)
        pq.write_table(
            table,
            shard_dir / f"clauses_{prefix}.parquet",
            compression="zstd",
        )
    if all_definitions:
        table = pa.Table.from_pylist(all_definitions)
        pq.write_table(
            table,
            shard_dir / f"definitions_{prefix}.parquet",
            compression="zstd",
        )
    if all_section_texts:
        table = pa.Table.from_pylist(all_section_texts)
        pq.write_table(
            table,
            shard_dir / f"section_text_{prefix}.parquet",
            compression="zstd",
        )
    if all_section_features:
        table = pa.Table.from_pylist(all_section_features)
        pq.write_table(
            table,
            shard_dir / f"section_features_{prefix}.parquet",
            compression="zstd",
        )
    if all_clause_features:
        table = pa.Table.from_pylist(all_clause_features)
        pq.write_table(
            table,
            shard_dir / f"clause_features_{prefix}.parquet",
            compression="zstd",
        )

    return {
        "docs": len(all_docs),
        "sections": len(all_sections),
        "clauses": len(all_clauses),
        "definitions": len(all_definitions),
        "section_texts": len(all_section_texts),
        "section_features": len(all_section_features),
        "clause_features": len(all_clause_features),
    }


# ---------------------------------------------------------------------------
# Parquet → DuckDB merge (NEW in v2)
# ---------------------------------------------------------------------------


def _merge_shards_to_duckdb(
    shard_dir: Path,
    output_path: Path,
    template_family_map: dict[str, str] | None = None,
) -> dict[str, int]:
    """Merge all Parquet shards into a single DuckDB file.

    Uses DuckDB's read_parquet() with glob patterns for bulk ingestion.
    This is orders of magnitude faster than row-by-row executemany().
    """
    import glob as globmod

    # Remove existing output (fresh build)
    if output_path.exists():
        output_path.unlink()

    conn = _duckdb.connect(str(output_path))
    conn.execute(_SCHEMA_DDL)

    stats: dict[str, int] = {}

    for table_name, needs_dedup, dedup_keys in _TABLE_MERGE_CONFIG:
        glob_pattern = str(shard_dir / f"{table_name}_*.parquet")
        matching_files = sorted(globmod.glob(glob_pattern))

        if not matching_files:
            log.warning("No shard files found for table '%s'", table_name)
            stats[table_name] = 0
            continue

        log.info(
            "Merging %d shard files for table '%s' ...",
            len(matching_files),
            table_name,
        )

        parquet_glob = str(shard_dir / f"{table_name}_*.parquet")
        table_cols = _TABLE_COLUMNS[table_name]
        select_cols = ", ".join(table_cols)
        if needs_dedup and dedup_keys:
            # Deterministic dedup: keep most recent shard file for duplicate keys.
            key_cols = ", ".join(dedup_keys)
            source_sql = f"""
                SELECT * EXCLUDE (rn, filename) FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY {key_cols}
                               ORDER BY filename DESC
                           ) AS rn
                    FROM read_parquet('{parquet_glob}', filename=true, union_by_name=true)
                ) WHERE rn = 1
            """
        else:
            source_sql = f"""
                SELECT * EXCLUDE (filename)
                FROM read_parquet('{parquet_glob}', filename=true)
            """

        conn.execute(f"""
            INSERT INTO {table_name} ({select_cols})
            SELECT {select_cols}
            FROM ({source_sql})
        """)

        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        stats[table_name] = count
        log.info("  %s: %d rows", table_name, count)

    # Apply template family map if provided
    if template_family_map:
        log.info("Applying %d template family mappings ...", len(template_family_map))
        for doc_id, family in template_family_map.items():
            conn.execute(
                "UPDATE documents SET template_family = ? WHERE doc_id = ?",
                [family, doc_id],
            )

    # Recompute clause_count from actual deduplicated clauses
    log.info("Recomputing clause counts from deduplicated data ...")
    conn.execute("""
        UPDATE documents SET clause_count = (
            SELECT COUNT(*) FROM clauses WHERE clauses.doc_id = documents.doc_id
        )
    """)

    # Filter child tables to only include doc_ids present in documents
    for child_table in [
        "sections", "clauses", "definitions", "section_text",
        "section_features", "clause_features",
    ]:
        before = conn.execute(f"SELECT COUNT(*) FROM {child_table}").fetchone()[0]
        conn.execute(f"""
            DELETE FROM {child_table}
            WHERE doc_id NOT IN (SELECT doc_id FROM documents)
        """)
        after = conn.execute(f"SELECT COUNT(*) FROM {child_table}").fetchone()[0]
        if before != after:
            log.info(
                "  Pruned %d orphaned rows from %s",
                before - after,
                child_table,
            )
            stats[child_table] = after

    conn.close()
    return stats


# ---------------------------------------------------------------------------
# S3 upload (same as v1)
# ---------------------------------------------------------------------------


def _upload_to_s3(
    local_path: str,
    s3_uri: str,
    region: str,
    profile: str | None = None,
) -> None:
    import boto3
    from boto3.s3.transfer import TransferConfig

    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    parts = s3_uri[5:].split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid S3 URI (missing key): {s3_uri}")
    bucket, key = parts[0], parts[1]

    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3")

    config = TransferConfig(
        multipart_threshold=64 * 1024 * 1024,
        multipart_chunksize=64 * 1024 * 1024,
        max_concurrency=10,
    )

    file_size = Path(local_path).stat().st_size
    log.info(
        "Uploading %s (%.1f MB) to %s ...",
        local_path,
        file_size / (1024 * 1024),
        s3_uri,
    )

    s3.upload_file(local_path, bucket, key, Config=config)
    log.info("Upload complete: %s", s3_uri)


# ---------------------------------------------------------------------------
# Template family map loader (same as v1)
# ---------------------------------------------------------------------------


def _load_template_family_map(path: Path) -> dict[str, str]:
    data = _load_json(path.read_bytes())
    if not isinstance(data, dict):
        return {}

    out: dict[str, str] = {}
    for doc_id, payload in data.items():
        if not isinstance(doc_id, str):
            continue
        if isinstance(payload, str):
            if payload:
                out[doc_id] = payload
            continue
        if isinstance(payload, dict):
            family = payload.get("template_family")
            if isinstance(family, str) and family:
                out[doc_id] = family
    return out


# ---------------------------------------------------------------------------
# Main orchestrator (REWRITTEN for v2)
# ---------------------------------------------------------------------------


def main() -> None:
    run_id = generate_run_id("ray_v2_corpus_build")
    t0 = time.time()

    parser = argparse.ArgumentParser(
        description="Build DuckDB corpus index from S3 documents using Ray (v2 — Parquet sharded).",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="S3 bucket name containing documents/ prefix",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Local path for output DuckDB file",
    )
    parser.add_argument(
        "--s3-upload",
        default=None,
        help="Optional S3 URI to upload finished DuckDB (e.g. s3://bucket/key.duckdb)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Documents per Parquet shard batch (default: 50)",
    )
    parser.add_argument(
        "--shards-dir",
        type=Path,
        default=None,
        help="Directory for Parquet shards (default: {output_dir}/shards/)",
    )
    parser.add_argument(
        "--keep-shards",
        action="store_true",
        help="Keep Parquet shard files after merge (default: delete)",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Checkpoint file path for resume (default: {output}.checkpoint.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N documents (for testing)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local Ray (ray.init()) instead of connecting to a cluster",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional AWS profile name",
    )
    parser.add_argument(
        "--template-classifications",
        type=Path,
        default=None,
        help="Optional doc_id -> template_family JSON for labeling",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file without confirmation",
    )
    parser.add_argument(
        "--one-per-cik",
        action="store_true",
        help=(
            "Keep only the most recent filing per CIK. "
            "Eliminates overweighting of borrowers with many filings."
        ),
    )
    parser.add_argument(
        "--doc-prefix",
        default="documents-trimmed",
        help=(
            "S3 key prefix for HTML documents "
            "(default: documents-trimmed)"
        ),
    )
    parser.add_argument(
        "--meta-prefix",
        default="metadata-trimmed",
        help=(
            "S3 key prefix for metadata sidecars "
            "(default: metadata-trimmed)"
        ),
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)

    output_path: Path = args.output.resolve()
    bucket: str = args.bucket.strip().removeprefix("s3://").rstrip("/")

    # Shard directory
    shard_dir: Path = args.shards_dir or (output_path.parent / "shards")
    shard_dir = shard_dir.resolve()

    # Checkpoint path
    checkpoint_path = args.checkpoint or Path(f"{output_path}.checkpoint.json")

    # Detect resume mode
    is_resume = checkpoint_path.exists()

    # Check output file
    if output_path.exists() and not args.force and not is_resume:
        response = input(
            f"Output file already exists: {output_path}\nOverwrite? [y/N] "
        )
        if response.strip().lower() not in ("y", "yes"):
            log.info("Aborted.")
            sys.exit(0)

    # Template family map
    template_family_map: dict[str, str] | None = None
    if args.template_classifications:
        tpath = args.template_classifications.resolve()
        if not tpath.exists():
            log.error("Template classifications file not found: %s", tpath)
            sys.exit(1)
        template_family_map = _load_template_family_map(tpath)
        log.info("Loaded %d template-family mappings", len(template_family_map))

    # -------------------------------------------------------------------
    # Step 1: Initialize Ray
    # -------------------------------------------------------------------
    if args.local:
        ray.init(ignore_reinit_error=True)
        log.info("Ray initialized in local mode")
    else:
        ray.init(address="auto")
        log.info("Connected to Ray cluster")

    cluster_resources = ray.cluster_resources()
    num_cpus = int(cluster_resources.get("CPU", 4))
    log.info(
        "Cluster resources: %d CPUs, %.1f GB memory",
        num_cpus,
        cluster_resources.get("memory", 0) / (1024**3),
    )

    try:
        # -------------------------------------------------------------------
        # Step 2: List S3 document keys
        # -------------------------------------------------------------------
        all_pairs = _list_document_keys(
            bucket, args.region, args.profile,
            doc_prefix=args.doc_prefix,
            meta_prefix=args.meta_prefix,
        )
        t_list_done = time.time()

        if args.limit and args.limit > 0:
            all_pairs = all_pairs[: args.limit]
            log.info("Limited to first %d documents", args.limit)

        if args.one_per_cik:
            doc_keys_only = [dk for dk, _ in all_pairs]
            kept_keys = set(dedup_by_cik(doc_keys_only, verbose=args.verbose))
            original_count = len(all_pairs)
            all_pairs = [(dk, mk) for dk, mk in all_pairs if dk in kept_keys]
            log.info(
                "CIK dedup: %d -> %d documents",
                original_count,
                len(all_pairs),
            )

        if not all_pairs:
            log.error("No HTML documents found in s3://%s/%s", bucket, args.doc_prefix)
            sys.exit(1)

        # -------------------------------------------------------------------
        # Step 3: Load checkpoint and filter
        # -------------------------------------------------------------------
        ckpt = _CheckpointManager(checkpoint_path)
        work_pairs = [
            (dk, mk)
            for dk, mk in all_pairs
            if not ckpt.is_processed(dk)
        ]

        log.info(
            "Work queue: %d documents (%d already processed, %d remaining)",
            len(all_pairs),
            ckpt.processed_count,
            len(work_pairs),
        )

        # -------------------------------------------------------------------
        # Step 4: Prepare shard directory
        # -------------------------------------------------------------------
        shard_dir.mkdir(parents=True, exist_ok=True)

        # Count existing shards for resume
        existing_shards = list(shard_dir.glob("documents_*.parquet"))
        shard_counter = len(existing_shards)
        if shard_counter > 0:
            log.info("Found %d existing shard files (resume mode)", shard_counter)

        merge_only = False
        if not work_pairs:
            if shard_counter > 0:
                log.info(
                    "No documents remaining, but shards exist. "
                    "Running merge-only recovery."
                )
                merge_only = True
            elif output_path.exists():
                log.info(
                    "All documents already processed and output exists: %s",
                    output_path,
                )
                manifest = build_manifest(
                    run_id=run_id,
                    db_path=output_path,
                    input_source={
                        "mode": "ray_local" if args.local else "ray_cluster",
                        "pipeline": "parquet_sharded_v2",
                        "bucket": bucket,
                        "region": args.region,
                        "limit": args.limit,
                        "resume": True,
                        "batch_size": args.batch_size,
                        "checkpoint_path": str(checkpoint_path),
                        "shards_dir": str(shard_dir),
                        "keep_shards": bool(args.keep_shards),
                        "s3_upload": args.s3_upload,
                    },
                    timings_sec={
                        "list_keys": round(t_list_done - t0, 3),
                        "process": 0.0,
                        "merge": 0.0,
                        "upload": 0.0,
                        "total": round(time.time() - t0, 3),
                    },
                    errors_count=ckpt.error_count,
                    stats={
                        "requested_docs": len(all_pairs),
                        "already_processed_docs": ckpt.processed_count,
                        "remaining_docs": 0,
                        "no_op": True,
                    },
                    git_commit=git_commit_hash(search_from=Path(__file__).resolve().parents[1]),
                )
                manifest_path, versioned_manifest_path = write_manifest(
                    output_path,
                    manifest,
                )
                log.info("Run manifest: %s", manifest_path)
                log.info("Versioned manifest: %s", versioned_manifest_path)
                ray.shutdown()
                return
            else:
                log.error(
                    "Checkpoint indicates all documents are processed, "
                    "but no shards and no output DB were found. "
                    "Remove checkpoint or rerun with --force."
                )
                sys.exit(1)

        # -------------------------------------------------------------------
        # Step 5: Process documents + write Parquet shards
        # -------------------------------------------------------------------
        wave_size = num_cpus * 4  # 4x CPUs in flight (reduced from 8x)
        total = len(work_pairs)
        submitted = 0
        completed = 0
        errors = 0
        batch_keys: list[str] = []
        result_batch: list[dict[str, Any]] = []  # Accumulate for Parquet writes
        cumulative_stats: dict[str, int] = {
            "docs": 0, "sections": 0, "clauses": 0,
            "definitions": 0, "section_texts": 0,
        }
        start_time = time.time()
        last_log_time = start_time

        if not merge_only:
            active_futures: list[ray.ObjectRef] = []  # type: ignore[type-arg]
            future_to_key: dict[ray.ObjectRef, str] = {}  # type: ignore[type-arg]
            pair_iter = iter(work_pairs)

            log.info(
                "Processing %d documents (wave_size=%d, cpus=%d, batch_size=%d) ...",
                total, wave_size, num_cpus, args.batch_size,
            )

            while submitted < total or active_futures:
                # Fill up to wave_size active tasks
                while len(active_futures) < wave_size and submitted < total:
                    doc_key, meta_key = next(pair_iter)
                    ref = process_document.remote(  # type: ignore[attr-defined]
                        bucket, doc_key, meta_key, args.region,
                    )
                    active_futures.append(ref)
                    future_to_key[ref] = doc_key
                    submitted += 1

                if not active_futures:
                    break

                # Wait for a batch of results (up to 100 at a time for high throughput)
                num_ready = min(100, len(active_futures))
                done, active_futures = ray.wait(
                    active_futures, num_returns=num_ready, timeout=60,
                )

                for ref in done:
                    doc_key = future_to_key.pop(ref)
                    try:
                        result: dict[str, Any] | None = ray.get(ref)
                    except Exception as exc:
                        log.warning("Task failed for %s: %s", doc_key, exc)
                        ckpt.mark_error(doc_key)
                        errors += 1
                        completed += 1
                        continue

                    if result is None:
                        ckpt.mark_error(doc_key)
                        errors += 1
                    else:
                        # Accumulate result for Parquet batch write
                        result_batch.append(result)
                        batch_keys.append(doc_key)

                    completed += 1

                # Write Parquet shard when batch is full
                if len(result_batch) >= args.batch_size:
                    shard_stats = _write_parquet_batch(
                        result_batch, shard_dir, shard_counter,
                    )
                    for k, v in shard_stats.items():
                        cumulative_stats[k] = cumulative_stats.get(k, 0) + v
                    shard_counter += 1
                    result_batch.clear()

                    # Save checkpoint after successful shard write
                    ckpt.mark_processed(batch_keys)
                    ckpt.save()
                    batch_keys.clear()

                # Progress logging every 30 seconds
                now = time.time()
                if now - last_log_time > 30 or completed == total:
                    elapsed_total = now - start_time
                    rate = completed / max(1, elapsed_total)
                    remaining = total - completed
                    eta_sec = remaining / max(0.01, rate)
                    pct = 100.0 * completed / total
                    log.info(
                        "Progress: %d/%d (%.1f%%) — %.1f docs/sec — "
                        "%d errors — %d shards written — ETA %.0fm%.0fs",
                        completed, total, pct, rate,
                        errors, shard_counter,
                        eta_sec // 60, eta_sec % 60,
                    )
                    last_log_time = now

            # Write final partial batch
            if result_batch:
                shard_stats = _write_parquet_batch(
                    result_batch, shard_dir, shard_counter,
                )
                for k, v in shard_stats.items():
                    cumulative_stats[k] = cumulative_stats.get(k, 0) + v
                shard_counter += 1
                result_batch.clear()

            # Final checkpoint save
            if batch_keys:
                ckpt.mark_processed(batch_keys)
                ckpt.save()

            processing_elapsed = time.time() - start_time
            log.info(
                "Processing complete in %.1fm: %d docs processed, %d errors, %d shards",
                processing_elapsed / 60,
                completed,
                errors,
                shard_counter,
            )
            log.info(
                "Shard totals: %d docs, %d sections, %d clauses, %d definitions",
                cumulative_stats["docs"],
                cumulative_stats["sections"],
                cumulative_stats["clauses"],
                cumulative_stats["definitions"],
            )
        else:
            processing_elapsed = 0.0

        # -------------------------------------------------------------------
        # Step 6: Merge Parquet shards → DuckDB
        # -------------------------------------------------------------------
        log.info("Merging %d shards into DuckDB at %s ...", shard_counter, output_path)
        merge_start = time.time()

        merge_stats = _merge_shards_to_duckdb(
            shard_dir, output_path, template_family_map,
        )

        merge_elapsed = time.time() - merge_start
        log.info("Merge complete in %.1fs", merge_elapsed)

        # -------------------------------------------------------------------
        # Step 7: Cleanup shards (unless --keep-shards)
        # -------------------------------------------------------------------
        if not args.keep_shards:
            log.info("Cleaning up shard directory: %s", shard_dir)
            shutil.rmtree(shard_dir, ignore_errors=True)

        # -------------------------------------------------------------------
        # Step 8: Upload to S3 if requested
        # -------------------------------------------------------------------
        if args.s3_upload:
            t_upload_start = time.time()
            _upload_to_s3(
                str(output_path),
                args.s3_upload,
                args.region,
                args.profile,
            )
            t_upload_done = time.time()
        else:
            t_upload_start = merge_start + merge_elapsed
            t_upload_done = merge_start + merge_elapsed

        manifest = build_manifest(
            run_id=run_id,
            db_path=output_path,
            input_source={
                "mode": "ray_local" if args.local else "ray_cluster",
                "pipeline": "parquet_sharded_v2",
                "bucket": bucket,
                "region": args.region,
                "limit": args.limit,
                "resume": is_resume,
                "batch_size": args.batch_size,
                "checkpoint_path": str(checkpoint_path),
                "shards_dir": str(shard_dir),
                "keep_shards": bool(args.keep_shards),
                "s3_upload": args.s3_upload,
            },
            timings_sec={
                "list_keys": round(t_list_done - t0, 3),
                "process": round(processing_elapsed, 3),
                "merge": round(merge_elapsed, 3),
                "upload": round(t_upload_done - t_upload_start, 3),
                "total": round(t_upload_done - t0, 3),
            },
            errors_count=errors,
            stats={
                "requested_docs": len(all_pairs),
                "already_processed_docs": ckpt.processed_count,
                "remaining_docs_at_start": len(work_pairs),
                "shards_written": shard_counter,
                "shard_totals": cumulative_stats,
                "merge_stats": merge_stats,
            },
            git_commit=git_commit_hash(search_from=Path(__file__).resolve().parents[1]),
        )
        manifest_path, versioned_manifest_path = write_manifest(output_path, manifest)
        log.info("Run manifest: %s", manifest_path)
        log.info("Versioned manifest: %s", versioned_manifest_path)

        # -------------------------------------------------------------------
        # Summary
        # -------------------------------------------------------------------
        total_elapsed = time.time() - start_time
        db_size_mb = output_path.stat().st_size / (1024 * 1024)
        print(
            f"\nCorpus build complete (v2 — Parquet sharded):\n"
            f"  Documents:   {merge_stats.get('documents', 0):,}\n"
            f"  Sections:    {merge_stats.get('sections', 0):,}\n"
            f"  Clauses:     {merge_stats.get('clauses', 0):,}\n"
            f"  Definitions: {merge_stats.get('definitions', 0):,}\n"
            f"  Sect. texts: {merge_stats.get('section_text', 0):,}\n"
            f"  Errors:      {errors:,}\n"
            f"  DuckDB size: {db_size_mb:,.1f} MB\n"
            f"  Total time:  {total_elapsed / 60:.1f} min "
            f"(processing: {processing_elapsed / 60:.1f}m, merge: {merge_elapsed:.1f}s)\n"
            f"  Output:      {output_path}\n"
            f"  Manifest:    {manifest_path}\n"
            f"  Gate:        python3 scripts/check_corpus_v2.py --db {output_path}\n",
            file=sys.stderr,
        )

    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
