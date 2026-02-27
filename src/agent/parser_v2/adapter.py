"""Adapter from parser_v2 solution to legacy clause/link contract."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent.parser_v2.graph_types import CandidateGraph
from agent.parser_v2.solution_types import SolverSolution


def adapt_solution_to_legacy_clause_nodes(
    solution: SolverSolution,
    graph: CandidateGraph,
    text: str,
    *,
    global_offset: int = 0,
) -> list[dict[str, Any]]:
    """Map parser_v2 solution to v1-style clause node dicts.

    Output fields preserve legacy keys used by downstream linking/review paths
    while adding parser_v2 status fields (`parse_status`, `abstain_reason_codes`,
    `solver_margin`).
    """

    candidate_by_id = {
        row.node_candidate_id: row
        for row in graph.node_candidates
    }
    children_by_parent: dict[str, list[str]] = defaultdict(list)
    siblings_by_parent: dict[str, list[str]] = defaultdict(list)
    for node in solution.nodes:
        siblings_by_parent[node.parent_id].append(node.clause_id)
        if node.parent_id:
            children_by_parent[node.parent_id].append(node.clause_id)
    for parent, values in children_by_parent.items():
        values.sort()
    for parent, values in siblings_by_parent.items():
        values.sort()

    rows: list[dict[str, Any]] = []
    for node in sorted(solution.nodes, key=lambda row: (row.span_start, row.clause_id)):
        candidate = candidate_by_id.get(node.node_candidate_id)
        raw_label = candidate.raw_label if candidate is not None else f"({node.clause_id.split('.')[-1]})"
        indent = (
            float(candidate.feature_vector.get("indentation", 0.0))
            if candidate is not None
            else 0.0
        )
        anchor_ok = bool(candidate.feature_vector.get("anchor", False)) if candidate is not None else False
        xref_suspected = bool(node.xref_suspected)
        start = int(node.span_start) + global_offset
        end = int(node.span_end) + global_offset
        if start < 0:
            start = 0
        if end < start:
            end = start
        header = text[node.span_end: min(len(text), node.span_end + 80)].strip()
        sibling_count = len(siblings_by_parent.get(node.parent_id, []))
        run_length_ok = sibling_count >= 2
        gap_ok = True
        demotion_reason = (
            "; ".join(node.abstain_reason_codes)
            if node.parse_status == "abstain"
            else ""
        )
        rows.append(
            {
                "id": node.clause_id,
                "label": raw_label,
                "depth": int(node.depth),
                "level_type": str(node.level_type),
                "span_start": start,
                "span_end": end,
                "header_text": header,
                "parent_id": str(node.parent_id),
                "children_ids": tuple(children_by_parent.get(node.clause_id, [])),
                "anchor_ok": anchor_ok,
                "run_length_ok": run_length_ok,
                "gap_ok": gap_ok,
                "indentation_score": round(indent, 4),
                "xref_suspected": xref_suspected,
                "is_structural_candidate": bool(node.is_structural_candidate),
                "parse_confidence": float(node.confidence_score),
                "demotion_reason": demotion_reason,
                "parse_status": node.parse_status,
                "abstain_reason_codes": tuple(node.abstain_reason_codes),
                "solver_margin": float(node.solver_margin),
            },
        )
    return rows


def build_link_contract_payload(
    solution: SolverSolution,
    graph: CandidateGraph,
    text: str,
    *,
    global_offset: int = 0,
) -> dict[str, Any]:
    """Build legacy-compatible link payload enriched with parser_v2 status."""

    nodes = adapt_solution_to_legacy_clause_nodes(
        solution,
        graph,
        text,
        global_offset=global_offset,
    )
    return {
        "parse_run_id": solution.parse_run_id,
        "parser_version": solution.parser_version,
        "section_key": solution.section_key,
        "section_parse_status": solution.section_parse_status,
        "section_reason_codes": tuple(solution.section_reason_codes),
        "critical_node_abstain_ratio": float(solution.critical_node_abstain_ratio),
        "abstained_token_ids": tuple(solution.abstained_token_ids),
        "nodes": nodes,
    }
