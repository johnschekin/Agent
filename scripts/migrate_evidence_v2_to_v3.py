#!/usr/bin/env python3
"""One-time migration utility: evidence_v2 JSONL -> evidence_v3 JSONL.

Idempotent behavior:
- evidence_v3 rows are passed through unchanged
- evidence_v2 rows are normalized to evidence_v3
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _normalize_v2_row(row: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(row.get("doc_id") or "").strip()
    section_number = str(row.get("section_number") or "").strip()
    heading = str(row.get("heading") or "").strip()
    clause_path = str(row.get("clause_path") or "__section__").strip() or "__section__"
    span_start = _to_int(row.get("span_start", row.get("char_start"))) or 0
    span_end = _to_int(row.get("span_end", row.get("char_end"))) or 0
    anchor_text = str(row.get("anchor_text") or heading).strip()
    text_sha256 = str(row.get("text_sha256") or "").strip()
    if not text_sha256:
        text_sha256 = hashlib.sha256(anchor_text.encode("utf-8")).hexdigest()

    document_id = str(row.get("document_id") or "").strip()
    if not document_id:
        document_id = hashlib.sha256(doc_id.encode("utf-8")).hexdigest()
    section_reference_key = str(row.get("section_reference_key") or "").strip()
    if not section_reference_key:
        section_reference_key = f"{document_id}:{section_number or 'unknown_section'}"
    clause_key = str(row.get("clause_key") or "").strip()
    if not clause_key:
        clause_key = f"{section_reference_key}:{clause_path}"
    chunk_id = str(row.get("chunk_id") or "").strip()
    if not chunk_id:
        payload = (
            f"{document_id}|{section_reference_key}|{clause_key}|"
            f"{span_start}|{span_end}|{text_sha256}"
        )
        chunk_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    score = _to_float(row.get("score")) or 0.0
    score_raw = _to_float(row.get("score_raw")) or score
    score_calibrated = _to_float(row.get("score_calibrated")) or score
    grounded = bool(row.get("grounded", True))
    policy_decision = str(row.get("policy_decision") or "").strip().lower()
    if policy_decision not in {"must", "review", "reject"}:
        if score_calibrated >= 0.8 and grounded:
            policy_decision = "must"
        elif score_calibrated >= 0.5 or not grounded:
            policy_decision = "review"
        else:
            policy_decision = "reject"
    reasons = row.get("policy_reasons", [])
    if not isinstance(reasons, list) or not reasons:
        reasons = [f"policy.{policy_decision}.derived"]

    return {
        "schema_version": "evidence_v3",
        "record_type": str(row.get("record_type") or "HIT"),
        "document_id": document_id,
        "section_reference_key": section_reference_key,
        "clause_key": clause_key,
        "ontology_node_id": str(row.get("ontology_node_id") or row.get("concept_id") or ""),
        "node_type": str(row.get("node_type") or ("section" if clause_path == "__section__" else "clause")),
        "section_path": str(row.get("section_path") or section_number),
        "clause_path": clause_path,
        "span_start": span_start,
        "span_end": span_end,
        "anchor_text": anchor_text,
        "text_sha256": text_sha256,
        "chunk_id": chunk_id,
        "score_raw": score_raw,
        "score_calibrated": score_calibrated,
        "threshold_profile_id": str(row.get("threshold_profile_id") or ""),
        "grounded": grounded,
        "policy_decision": policy_decision,
        "policy_reasons": reasons,
        "run_id": str(row.get("run_id") or ""),
        "corpus_snapshot_id": str(row.get("corpus_snapshot_id") or ""),
        "corpus_version": str(row.get("corpus_version") or ""),
        "parser_version": str(row.get("parser_version") or ""),
        "ontology_version": str(row.get("ontology_version") or ""),
        "ruleset_version": str(row.get("ruleset_version") or ""),
        "git_sha": str(row.get("git_sha") or ""),
        "source_document_path": str(row.get("source_document_path") or ""),
        "created_at_utc": str(row.get("created_at_utc") or row.get("created_at") or ""),
        "doc_id": doc_id,
        "section_number": section_number,
        "strategy_version": row.get("strategy_version"),
        "source_tool": str(row.get("source_tool") or ""),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate evidence_v2 jsonl payloads to evidence_v3.")
    parser.add_argument("--input", required=True, help="Input JSONL path")
    parser.add_argument("--output", required=True, help="Output JSONL path")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output file")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        raise SystemExit(f"Input file does not exist: {in_path}")

    rows_out: list[dict[str, Any]] = []
    counts = {"v2_to_v3": 0, "v3_passthrough": 0, "other_skipped": 0}
    for line in in_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            counts["other_skipped"] += 1
            continue
        schema = str(row.get("schema_version") or "")
        if schema == "evidence_v3":
            rows_out.append(row)
            counts["v3_passthrough"] += 1
            continue
        if schema == "evidence_v2" or not schema:
            rows_out.append(_normalize_v2_row(row))
            counts["v2_to_v3"] += 1
            continue
        counts["other_skipped"] += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        with out_path.open("w") as f:
            for row in rows_out:
                f.write(json.dumps(row))
                f.write("\n")

    report = {
        "status": "dry_run" if args.dry_run else "ok",
        "input": str(in_path),
        "output": str(out_path),
        "counts": counts,
        "input_sha256": _file_sha256(in_path),
        "output_sha256": _file_sha256(out_path) if out_path.exists() else "",
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

