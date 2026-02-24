#!/usr/bin/env python3
"""Sync corpus documents and metadata from S3.

Usage:
    python3 scripts/sync_corpus.py \
      --bucket edgar-pipeline-documents-216213517387 \
      --local-dir corpus/ \
      --parallel 32

Outputs structured JSON to stdout; progress and command logs go to stderr.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _normalize_bucket(bucket: str) -> str:
    cleaned = bucket.strip()
    if cleaned.startswith("s3://"):
        cleaned = cleaned[5:]
    return cleaned.rstrip("/")


def _build_aws_prefix(*, profile: str | None, region: str) -> list[str]:
    cmd = ["aws"]
    if profile:
        cmd.extend(["--profile", profile])
    if region:
        cmd.extend(["--region", region])
    return cmd


def _run_sync_command(
    *,
    label: str,
    src: str,
    dst: Path,
    aws_prefix: list[str],
    dry_run: bool,
    env: dict[str, str],
) -> dict[str, Any]:
    dst.mkdir(parents=True, exist_ok=True)
    cmd = aws_prefix + [
        "s3",
        "sync",
        src,
        str(dst),
        "--only-show-errors",
    ]
    if dry_run:
        cmd.append("--dryrun")

    log(f"[{label}] Running: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
    )
    result: dict[str, Any] = {
        "label": label,
        "source": src,
        "destination": str(dst),
        "command": cmd,
        "returncode": proc.returncode,
        "status": "ok" if proc.returncode == 0 else "error",
    }
    if proc.stdout.strip():
        result["stdout"] = proc.stdout.strip()
    if proc.stderr.strip():
        result["stderr"] = proc.stderr.strip()
    return result


_ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")


def _list_s3_keys(
    *,
    bucket: str,
    prefix: str,
    aws_prefix: list[str],
    env: dict[str, str],
) -> list[str]:
    cmd = aws_prefix + [
        "s3api",
        "list-objects-v2",
        "--bucket",
        bucket,
        "--prefix",
        prefix,
        "--query",
        "Contents[].Key",
        "--output",
        "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"Failed listing {prefix}: {stderr}")
    raw = proc.stdout.strip() or "[]"
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return [str(k) for k in data if isinstance(k, str)]


def _meta_key_for_doc_key(doc_key: str) -> str:
    # documents/cik=.../{accession}_{exhibit}.htm -> metadata/cik=.../{accession}.meta.json
    meta_key = doc_key.replace("documents/", "metadata/", 1)
    stem = Path(meta_key).stem
    accession_match = _ACCESSION_RE.search(stem)
    if accession_match:
        accession = accession_match.group(1)
        return str(Path(meta_key).with_name(f"{accession}.meta.json"))
    return str(Path(meta_key).with_suffix(".meta.json"))


def _copy_s3_key(
    *,
    bucket: str,
    key: str,
    local_dir: Path,
    aws_prefix: list[str],
    dry_run: bool,
    env: dict[str, str],
) -> dict[str, Any]:
    dst = local_dir / key
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() and dst.stat().st_size > 0:
        return {"key": key, "status": "skipped_existing"}

    if dry_run:
        return {"key": key, "status": "dry_run"}

    src = f"s3://{bucket}/{key}"
    cmd = aws_prefix + ["s3", "cp", src, str(dst), "--only-show-errors"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return {
            "key": key,
            "status": "error",
            "stderr": proc.stderr.strip(),
        }
    return {"key": key, "status": "ok"}


def _sync_limited(
    *,
    bucket: str,
    local_dir: Path,
    aws_prefix: list[str],
    env: dict[str, str],
    dry_run: bool,
    limit: int,
    parallel: int,
) -> dict[str, Any]:
    doc_keys = _list_s3_keys(
        bucket=bucket,
        prefix="documents/",
        aws_prefix=aws_prefix,
        env=env,
    )
    doc_keys = sorted(
        k for k in doc_keys if k.lower().endswith((".htm", ".html"))
    )[:limit]

    meta_keys = sorted({_meta_key_for_doc_key(k) for k in doc_keys})
    all_keys = doc_keys + meta_keys

    log(
        f"[limited] Selected {len(doc_keys)} document keys and "
        f"{len(meta_keys)} metadata keys"
    )

    results: list[dict[str, Any]] = []
    max_workers = max(1, parallel)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(
                _copy_s3_key,
                bucket=bucket,
                key=key,
                local_dir=local_dir,
                aws_prefix=aws_prefix,
                dry_run=dry_run,
                env=env,
            )
            for key in all_keys
        ]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    status_counts: dict[str, int] = {}
    for r in results:
        status = str(r.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "mode": "limited",
        "limit": limit,
        "documents_selected": len(doc_keys),
        "metadata_selected": len(meta_keys),
        "status_counts": status_counts,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync corpus documents and metadata from S3."
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="S3 bucket name (with or without s3:// prefix).",
    )
    parser.add_argument(
        "--local-dir",
        type=Path,
        required=True,
        help="Local corpus root directory (documents/ and metadata/ will be created under it).",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=32,
        help="Desired transfer parallelism hint for AWS CLI (default: 32).",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region for the S3 bucket (default: us-east-1).",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Optional AWS profile name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned sync operations without downloading files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Download only the first N documents (+ matching metadata).",
    )
    args = parser.parse_args()

    if shutil.which("aws") is None:
        log("Error: aws CLI not found on PATH.")
        sys.exit(1)

    bucket = _normalize_bucket(args.bucket)
    local_dir = args.local_dir.resolve()
    local_dir.mkdir(parents=True, exist_ok=True)

    aws_prefix = _build_aws_prefix(profile=args.profile, region=args.region)
    env = os.environ.copy()
    # Advisory hint for CLI transfer concurrency (recognized by AWS CLI v2).
    env["AWS_MAX_CONCURRENT_REQUESTS"] = str(max(1, args.parallel))

    if args.limit is not None and args.limit > 0:
        limited = _sync_limited(
            bucket=bucket,
            local_dir=local_dir,
            aws_prefix=aws_prefix,
            env=env,
            dry_run=args.dry_run,
            limit=args.limit,
            parallel=args.parallel,
        )
        status = "success"
        if limited["status_counts"].get("error", 0) > 0:
            status = "error"
        output = {
            "status": status,
            "bucket": bucket,
            "region": args.region,
            "profile": args.profile,
            "local_dir": str(local_dir),
            "parallel_hint": args.parallel,
            "dry_run": args.dry_run,
            "mode": "limited",
            "limited_result": limited,
        }
    else:
        documents_src = f"s3://{bucket}/documents"
        metadata_src = f"s3://{bucket}/metadata"
        documents_dst = local_dir / "documents"
        metadata_dst = local_dir / "metadata"

        doc_result = _run_sync_command(
            label="documents",
            src=documents_src,
            dst=documents_dst,
            aws_prefix=aws_prefix,
            dry_run=args.dry_run,
            env=env,
        )
        meta_result = _run_sync_command(
            label="metadata",
            src=metadata_src,
            dst=metadata_dst,
            aws_prefix=aws_prefix,
            dry_run=args.dry_run,
            env=env,
        )

        status = (
            "success"
            if doc_result["status"] == "ok" and meta_result["status"] == "ok"
            else "error"
        )
        output = {
            "status": status,
            "bucket": bucket,
            "region": args.region,
            "profile": args.profile,
            "local_dir": str(local_dir),
            "parallel_hint": args.parallel,
            "dry_run": args.dry_run,
            "mode": "full_sync",
            "sync_results": [doc_result, meta_result],
        }
    dump_json(output)
    if status != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
