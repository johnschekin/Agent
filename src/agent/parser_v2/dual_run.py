"""Dual-run utilities for parser_v1 vs parser_v2 shadow evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent.clause_parser import parse_clauses
from agent.parser_v2.adapter import build_link_contract_payload
from agent.parser_v2.compare_v1 import compare_solver_vs_v1
from agent.parser_v2.graph_builder import build_candidate_graph
from agent.parser_v2.solution_types import solution_to_dict
from agent.parser_v2.solver import solve_candidate_graph


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _extract_row_payload(row: dict[str, Any], idx: int) -> dict[str, Any]:
    text_obj = row.get("text") or {}
    source = row.get("source") or {}
    fixture_id = str(row.get("fixture_id") or f"fixture_{idx:06d}")
    raw_text = str(text_obj.get("raw_text") or row.get("raw_text") or "")
    char_start = int(text_obj.get("char_start") or 0)
    doc_id = str(source.get("doc_id") or row.get("doc_id") or f"doc_{idx:06d}")
    section_number = str(source.get("section_number") or row.get("section_number") or "")
    section_key = f"{doc_id}::{section_number or 'section'}::{fixture_id}"
    return {
        "fixture_id": fixture_id,
        "doc_id": doc_id,
        "section_number": section_number,
        "section_key": section_key,
        "raw_text": raw_text,
        "char_start": char_start,
    }


def _v1_nodes_to_dict(nodes: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(node.id),
            "label": str(node.label),
            "parent_id": str(node.parent_id),
            "depth": int(node.depth),
            "level_type": str(node.level_type),
            "span_start": int(node.span_start),
            "span_end": int(node.span_end),
            "is_structural_candidate": bool(node.is_structural_candidate),
            "parse_confidence": float(node.parse_confidence),
        }
        for node in nodes
    ]


def run_dual_run(
    fixtures_path: Path,
    *,
    limit: int | None = None,
    sidecar_out: Path | None = None,
    overwrite_sidecar: bool = False,
) -> dict[str, Any]:
    """Run parser_v1 vs parser_v2 dual-run and optionally persist sidecar JSONL."""

    rows = _iter_jsonl(fixtures_path)
    if limit is not None and limit >= 0:
        rows = rows[:limit]

    sidecar_records: list[dict[str, Any]] = []
    section_status_counts: dict[str, int] = {"accepted": 0, "review": 0, "abstain": 0}
    overlap_acc = 0.0
    processed = 0

    for idx, row in enumerate(rows):
        payload = _extract_row_payload(row, idx)
        raw_text = payload["raw_text"]
        if not raw_text:
            continue
        char_start = int(payload["char_start"])
        section_key = str(payload["section_key"])
        graph = build_candidate_graph(raw_text)
        solution = solve_candidate_graph(graph, section_key=section_key)
        adapted = build_link_contract_payload(
            solution,
            graph,
            raw_text,
            global_offset=char_start,
        )
        v1_nodes = parse_clauses(raw_text, global_offset=char_start)
        v1_ids = {str(node.id) for node in v1_nodes}
        v2_ids = {str(node["id"]) for node in adapted["nodes"]}
        overlap = (len(v1_ids & v2_ids) / max(1, len(v1_ids | v2_ids)))
        overlap_acc += overlap
        processed += 1

        section_status = str(solution.section_parse_status)
        if section_status not in section_status_counts:
            section_status_counts[section_status] = 0
        section_status_counts[section_status] += 1

        sidecar_records.append(
            {
                "fixture_id": payload["fixture_id"],
                "doc_id": payload["doc_id"],
                "section_number": payload["section_number"],
                "section_key": section_key,
                "raw_text_sha256": _sha256_text(raw_text),
                "parser_v1": {
                    "node_count": len(v1_nodes),
                    "nodes": _v1_nodes_to_dict(v1_nodes),
                },
                "parser_v2": {
                    "solution": solution_to_dict(solution),
                    "adapted_link_payload": adapted,
                },
                "comparison": compare_solver_vs_v1(raw_text, section_key=section_key),
                "id_overlap_ratio": round(overlap, 6),
            },
        )

    avg_overlap = round(overlap_acc / max(1, processed), 6)
    report = {
        "fixtures_path": str(fixtures_path),
        "processed_sections": processed,
        "section_status_counts": section_status_counts,
        "avg_id_overlap_ratio": avg_overlap,
        "sidecar_records": len(sidecar_records),
    }

    if sidecar_out is not None:
        sidecar_out.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if overwrite_sidecar else "a"
        with sidecar_out.open(mode, encoding="utf-8") as f:
            for record in sidecar_records:
                f.write(json.dumps(record) + "\n")
        report["sidecar_path"] = str(sidecar_out)

    return report
