#!/usr/bin/env python3
"""Save normalized v2 evidence rows with provenance to workspace JSONL files.

Usage:
    python3 scripts/evidence_collector.py \
      --matches matches.json \
      --concept-id debt_capacity.indebtedness \
      --workspace workspaces/indebtedness

Accepts either:
1. A JSON array of match/not-found rows, or
2. A tool payload object (e.g., pattern_tester output with `matches` and
   optional `miss_records`).

Outputs structured JSON to stdout, human messages to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def dump_json_bytes(obj: object) -> bytes:
        return orjson.dumps(obj, default=str)

    def load_json(path: Path) -> object:
        return orjson.loads(path.read_bytes())
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def dump_json_bytes(obj: object) -> bytes:
        return json.dumps(obj, default=str).encode("utf-8")

    def load_json(path: Path) -> object:
        with open(path) as f:
            return json.load(f)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _detect_source_tool(payload: object, matches_path: Path) -> str:
    if isinstance(payload, dict):
        schema = str(payload.get("schema_version", "")).lower()
        if "pattern_tester" in schema:
            return "pattern_tester"
        if "child_locator" in schema:
            return "child_locator"
        if "strategy_writer" in schema:
            return "strategy_writer"
        if payload.get("miss_summary") is not None or payload.get("hit_summary") is not None:
            return "pattern_tester"
    name = matches_path.name.lower()
    if "pattern" in name:
        return "pattern_tester"
    if "child" in name:
        return "child_locator"
    return "unknown"


def _update_workspace_checkpoint_after_evidence(
    workspace: Path,
    *,
    concept_id: str,
    evidence_file: Path,
    run_id: str,
    strategy_version: int | None,
    records_written: int,
) -> dict[str, Any]:
    checkpoint_path = workspace / "checkpoint.json"
    payload: dict[str, Any] = {}
    if checkpoint_path.exists():
        try:
            loaded = load_json(checkpoint_path)
            if isinstance(loaded, dict):
                payload = dict(loaded)
        except Exception:
            payload = {}

    status = str(payload.get("status", "")).strip().lower()
    if status not in {"completed", "locked"}:
        status = "running"

    payload["family"] = str(payload.get("family") or workspace.name)
    payload["status"] = status
    payload["current_concept_id"] = concept_id
    payload["last_concept_id"] = concept_id
    payload["last_evidence_file"] = str(evidence_file)
    payload["last_evidence_run_id"] = run_id
    payload["last_evidence_records"] = int(records_written)
    payload["last_evidence_at"] = _now_iso()
    payload["last_update"] = payload["last_evidence_at"]
    if strategy_version is not None:
        try:
            sv = int(strategy_version)
            prev = _as_int(payload.get("last_strategy_version")) or 0
            payload["last_strategy_version"] = max(prev, sv)
        except (TypeError, ValueError):
            pass

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(payload, indent=2, default=str))
    return {
        "path": str(checkpoint_path),
        "status": str(payload.get("status", "")),
        "last_evidence_records": int(payload.get("last_evidence_records", 0)),
        "last_strategy_version": _as_int(payload.get("last_strategy_version")),
    }


def _extract_rows(
    payload: object,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if isinstance(payload, list):
        hits = [row for row in payload if isinstance(row, dict)]
        return hits, [], {}

    if not isinstance(payload, dict):
        return [], [], {}

    matches = _as_list(payload.get("matches"))
    if not matches:
        matches = _as_list(payload.get("results"))
    hits = [row for row in matches if isinstance(row, dict)]

    miss_rows = _as_list(payload.get("miss_records"))
    if not miss_rows:
        miss_rows = _as_list(payload.get("not_found_records"))
    misses = [row for row in miss_rows if isinstance(row, dict)]
    return hits, misses, payload


def _normalize_hit_or_not_found(
    *,
    row: dict[str, Any],
    ontology_node_id: str,
    run_id: str,
    strategy_version: int | None,
    source_tool: str,
    created_at: str,
) -> dict[str, Any] | None:
    doc_id = str(row.get("doc_id", "")).strip()
    if not doc_id:
        return None

    record_type = str(row.get("record_type", "")).strip().upper()
    if not record_type:
        if (
            str(row.get("match_type", "")).strip().lower() == "not_found"
            or row.get("not_found_reason")
        ):
            record_type = "NOT_FOUND"
        else:
            record_type = "HIT"
    if record_type not in {"HIT", "NOT_FOUND"}:
        record_type = "HIT"

    char_start = row.get("char_start")
    if char_start is None:
        char_start = row.get("span_start")
    char_end = row.get("char_end")
    if char_end is None:
        char_end = row.get("span_end")

    section_number = (
        row.get("section_number")
        or row.get("section")
        or row.get("parent_section")
        or ""
    )
    heading = row.get("heading") or row.get("header_text") or row.get("section_heading") or ""
    score = row.get("score")
    if score is None:
        score = row.get("match_score")
    if score is None:
        score = row.get("confidence_final")

    confidence_components = _as_dict(row.get("confidence_components"))
    confidence_breakdown = _as_dict(row.get("confidence_breakdown"))
    if not confidence_breakdown:
        confidence_breakdown = {
            "final": _as_float(row.get("confidence_final")) or _as_float(score) or 0.0,
            "components": {
                k: _as_float(v) if _as_float(v) is not None else v
                for k, v in confidence_components.items()
            },
        }
    else:
        if "final" not in confidence_breakdown:
            confidence_breakdown["final"] = (
                _as_float(row.get("confidence_final"))
                or _as_float(score)
            )
        if "components" not in confidence_breakdown and confidence_components:
            confidence_breakdown["components"] = {
                k: _as_float(v) if _as_float(v) is not None else v
                for k, v in confidence_components.items()
            }

    outlier = _as_dict(row.get("outlier"))
    if not outlier:
        outlier = {
            "level": "none",
            "score": 0.0,
            "flags": [],
        }

    return {
        "schema_version": "evidence_v2",
        "record_type": record_type,
        "ontology_node_id": ontology_node_id,
        "concept_id": ontology_node_id,  # legacy compatibility
        "run_id": run_id,
        "strategy_version": strategy_version,
        "source_tool": source_tool,
        "created_at": created_at,
        "doc_id": doc_id,
        "template_family": str(row.get("template_family", "") or ""),
        "section_number": str(section_number),
        "heading": str(heading),
        "clause_path": str(row.get("clause_path", "") or ""),
        "char_start": _as_int(char_start),
        "char_end": _as_int(char_end),
        "match_type": str(row.get("match_type", row.get("match_method", "")) or ""),
        "score": _as_float(score),
        "confidence_breakdown": confidence_breakdown,
        "outlier": outlier,
        "scope_parity": _as_dict(row.get("scope_parity")),
        "preemption": _as_dict(row.get("preemption")),
        "not_found_reason": str(row.get("not_found_reason", "") or ""),
    }


def _normalize_not_found_from_miss(
    *,
    row: dict[str, Any],
    ontology_node_id: str,
    run_id: str,
    strategy_version: int | None,
    source_tool: str,
    created_at: str,
) -> dict[str, Any] | None:
    doc_id = str(row.get("doc_id", "")).strip()
    if not doc_id:
        return None
    return {
        "schema_version": "evidence_v2",
        "record_type": "NOT_FOUND",
        "ontology_node_id": ontology_node_id,
        "concept_id": ontology_node_id,
        "run_id": run_id,
        "strategy_version": strategy_version,
        "source_tool": source_tool,
        "created_at": created_at,
        "doc_id": doc_id,
        "template_family": str(row.get("template_family", "") or ""),
        "section_number": str(row.get("section_number", row.get("best_section", "")) or ""),
        "heading": str(row.get("best_heading", row.get("heading", "")) or ""),
        "clause_path": str(row.get("clause_path", "") or ""),
        "char_start": _as_int(row.get("char_start", row.get("span_start"))),
        "char_end": _as_int(row.get("char_end", row.get("span_end"))),
        "match_type": "not_found",
        "score": _as_float(row.get("best_score", row.get("score"))),
        "confidence_breakdown": {
            "final": _as_float(row.get("confidence_final", row.get("best_score"))) or 0.0,
            "components": _as_dict(row.get("confidence_components")),
        },
        "outlier": _as_dict(row.get("outlier")) or {
            "level": "none",
            "score": 0.0,
            "flags": [],
        },
        "scope_parity": _as_dict(row.get("scope_parity")),
        "preemption": _as_dict(row.get("preemption")),
        "not_found_reason": str(
            row.get("not_found_reason", "no_match_found_for_document")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save normalized evidence v2 rows with provenance."
    )
    parser.add_argument(
        "--matches",
        required=True,
        help="JSON file with match results (pattern_tester or child_locator output).",
    )
    parser.add_argument(
        "--concept-id",
        required=True,
        help="Ontology node id for provenance tracking.",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Workspace directory path.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run identifier override (otherwise sourced or auto-generated).",
    )
    parser.add_argument(
        "--strategy-version",
        type=int,
        default=None,
        help="Optional strategy version override.",
    )
    parser.add_argument(
        "--source-tool",
        default=None,
        help="Optional source tool override (pattern_tester/child_locator/etc).",
    )
    parser.add_argument(
        "--skip-not-found",
        action="store_true",
        help="Do not emit NOT_FOUND rows from miss records or explicit not-found matches.",
    )
    args = parser.parse_args()

    matches_path = Path(args.matches)
    if not matches_path.exists():
        log(f"Error: matches file not found at {matches_path}")
        sys.exit(1)

    workspace = Path(args.workspace)
    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    payload = load_json(matches_path)
    hit_rows, miss_rows, payload_meta = _extract_rows(payload)
    if isinstance(payload, list) and not hit_rows:
        log("Error: matches list contains no object rows")
        sys.exit(1)

    source_tool = args.source_tool or _detect_source_tool(payload, matches_path)
    run_id = (
        args.run_id
        or (
            str(payload_meta.get("run_id", "")).strip()
            if payload_meta
            else ""
        )
        or f"evidence_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    )
    strategy_version = args.strategy_version
    if strategy_version is None and payload_meta:
        sv_raw = payload_meta.get("strategy_version")
        strategy_version = _as_int(sv_raw)
    created_at = _now_iso()

    normalized: list[dict[str, Any]] = []
    skipped = 0

    for row in hit_rows:
        record = _normalize_hit_or_not_found(
            row=row,
            ontology_node_id=args.concept_id,
            run_id=run_id,
            strategy_version=strategy_version,
            source_tool=source_tool,
            created_at=created_at,
        )
        if record is None:
            skipped += 1
            continue
        if args.skip_not_found and record["record_type"] == "NOT_FOUND":
            continue
        normalized.append(record)

    if not args.skip_not_found:
        for row in miss_rows:
            record = _normalize_not_found_from_miss(
                row=row,
                ontology_node_id=args.concept_id,
                run_id=run_id,
                strategy_version=strategy_version,
                source_tool=source_tool,
                created_at=created_at,
            )
            if record is None:
                skipped += 1
                continue
            normalized.append(record)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    evidence_filename = f"{args.concept_id}_{timestamp}.jsonl"
    evidence_file = evidence_dir / evidence_filename

    hit_count = 0
    not_found_count = 0
    unique_docs: set[str] = set()

    with open(evidence_file, "wb") as f:
        for record in normalized:
            f.write(dump_json_bytes(record))
            f.write(b"\n")
            unique_docs.add(str(record["doc_id"]))
            if record["record_type"] == "NOT_FOUND":
                not_found_count += 1
            else:
                hit_count += 1

    if skipped > 0:
        log(f"Skipped {skipped} row(s) with missing required fields")

    log(
        f"Wrote {len(normalized)} evidence row(s): {hit_count} HIT, "
        f"{not_found_count} NOT_FOUND across {len(unique_docs)} doc(s)"
    )

    summary = {
        "schema_version": "evidence_v2",
        "ontology_node_id": args.concept_id,
        "run_id": run_id,
        "strategy_version": strategy_version,
        "source_tool": source_tool,
        "evidence_file": str(evidence_file),
        "records_written": len(normalized),
        "hit_records": hit_count,
        "not_found_records": not_found_count,
        "unique_docs": len(unique_docs),
    }
    checkpoint_update = _update_workspace_checkpoint_after_evidence(
        workspace,
        concept_id=args.concept_id,
        evidence_file=evidence_file,
        run_id=run_id,
        strategy_version=strategy_version,
        records_written=len(normalized),
    )
    summary["checkpoint_update"] = checkpoint_update
    dump_json(summary)


if __name__ == "__main__":
    main()
