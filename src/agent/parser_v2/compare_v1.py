"""Solver-v2 vs parser-v1 comparison helpers."""

from __future__ import annotations

from agent.clause_parser import parse_clauses
from agent.parser_v2.solution_types import solution_to_dict
from agent.parser_v2.solver import solve_parser_v2


def compare_solver_vs_v1(text: str, *, section_key: str = "section::compare") -> dict[str, object]:
    """Compare parser_v1 clause output to parser_v2 solver output for one section."""

    nodes_v1 = parse_clauses(text)
    solution = solve_parser_v2(text, section_key=section_key)
    nodes_v2 = solution.nodes

    v1_ids = [node.id for node in nodes_v1]
    v2_ids = [node.clause_id for node in nodes_v2]
    set_v1 = set(v1_ids)
    set_v2 = set(v2_ids)

    return {
        "section_key": section_key,
        "counts": {
            "v1_total_nodes": len(nodes_v1),
            "v2_total_nodes": len(nodes_v2),
            "v2_abstained_tokens": len(solution.abstained_token_ids),
        },
        "status": {
            "section_parse_status": solution.section_parse_status,
            "critical_node_abstain_ratio": solution.critical_node_abstain_ratio,
            "section_reason_codes": list(solution.section_reason_codes),
        },
        "id_overlap": {
            "intersection_count": len(set_v1.intersection(set_v2)),
            "only_v1_count": len(set_v1.difference(set_v2)),
            "only_v2_count": len(set_v2.difference(set_v1)),
        },
        "only_v1_clause_ids": sorted(set_v1.difference(set_v2)),
        "only_v2_clause_ids": sorted(set_v2.difference(set_v1)),
        "v2_solution": solution_to_dict(solution),
    }
