"""Solver output types for parser_v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


type ParseStatus = Literal["accepted", "review", "abstain"]


@dataclass(frozen=True, slots=True)
class SolvedClauseNode:
    """Derived node record from solver selections."""

    node_candidate_id: str
    clause_id: str
    parent_id: str
    depth: int
    level_type: str
    span_start: int
    span_end: int
    is_structural_candidate: bool
    xref_suspected: bool
    parse_status: ParseStatus
    abstain_reason_codes: tuple[str, ...]
    solver_margin: float
    confidence_score: float

    def __post_init__(self) -> None:
        if self.span_start < 0:
            raise ValueError("span_start must be >= 0")
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be > span_start")
        if self.depth <= 0:
            raise ValueError("depth must be > 0")
        if self.parse_status == "abstain" and not self.abstain_reason_codes:
            raise ValueError("abstain node must include reason codes")


@dataclass(frozen=True, slots=True)
class SolverSolution:
    """Full solver solution output contract."""

    parse_run_id: str
    parser_version: str
    section_key: str
    selected_node_candidates: tuple[str, ...]
    selected_parent_edges: tuple[str, ...]
    abstained_token_ids: tuple[str, ...]
    objective_score: float
    objective_components: dict[str, float]
    top_k_alternatives: tuple[dict[str, object], ...]
    solver_diagnostics: dict[str, object]
    nodes: tuple[SolvedClauseNode, ...]
    section_parse_status: ParseStatus
    section_reason_codes: tuple[str, ...]
    critical_node_abstain_ratio: float
    top1_score: float
    top2_score: float
    margin_abs: float
    margin_ratio: float


def solution_to_dict(solution: SolverSolution) -> dict[str, object]:
    """Serialize solution for deterministic snapshots."""

    return {
        "parse_run_id": solution.parse_run_id,
        "parser_version": solution.parser_version,
        "section_key": solution.section_key,
        "selected_node_candidates": list(solution.selected_node_candidates),
        "selected_parent_edges": list(solution.selected_parent_edges),
        "abstained_token_ids": list(solution.abstained_token_ids),
        "objective_score": solution.objective_score,
        "objective_components": dict(sorted(solution.objective_components.items())),
        "top_k_alternatives": list(solution.top_k_alternatives),
        "solver_diagnostics": dict(solution.solver_diagnostics),
        "nodes": [
            {
                "node_candidate_id": node.node_candidate_id,
                "clause_id": node.clause_id,
                "parent_id": node.parent_id,
                "depth": node.depth,
                "level_type": node.level_type,
                "span_start": node.span_start,
                "span_end": node.span_end,
                "is_structural_candidate": node.is_structural_candidate,
                "xref_suspected": node.xref_suspected,
                "parse_status": node.parse_status,
                "abstain_reason_codes": list(node.abstain_reason_codes),
                "solver_margin": node.solver_margin,
                "confidence_score": node.confidence_score,
            }
            for node in solution.nodes
        ],
        "section_parse_status": solution.section_parse_status,
        "section_reason_codes": list(solution.section_reason_codes),
        "critical_node_abstain_ratio": solution.critical_node_abstain_ratio,
        "top1_score": solution.top1_score,
        "top2_score": solution.top2_score,
        "margin_abs": solution.margin_abs,
        "margin_ratio": solution.margin_ratio,
    }
