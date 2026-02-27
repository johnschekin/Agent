"""Candidate graph types for parser_v2."""

from __future__ import annotations

from dataclasses import dataclass

from agent.parser_v2.types import CandidateType


type FeatureValue = bool | int | float | str


@dataclass(frozen=True, slots=True)
class ClauseNodeCandidate:
    """A token/type interpretation candidate before solving."""

    node_candidate_id: str
    token_id: str
    token_index: int
    level_type: CandidateType
    ordinal: int
    depth_hint: int
    span_start: int
    span_end: int
    feature_vector: dict[str, FeatureValue]

    def __post_init__(self) -> None:
        if not self.node_candidate_id:
            raise ValueError("node_candidate_id cannot be empty")
        if not self.token_id:
            raise ValueError("token_id cannot be empty")
        if self.token_index < 0:
            raise ValueError("token_index must be >= 0")
        if self.ordinal <= 0:
            raise ValueError("ordinal must be > 0")
        if self.depth_hint <= 0:
            raise ValueError("depth_hint must be > 0")
        if self.span_start < 0:
            raise ValueError("span_start must be >= 0")
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be > span_start")


@dataclass(frozen=True, slots=True)
class ParentEdgeCandidate:
    """Candidate parent edge from child to parent or root."""

    edge_id: str
    child_candidate_id: str
    parent_candidate_id: str
    root: bool
    hard_valid: bool
    hard_invalid_reasons: tuple[str, ...]
    soft_score_components: dict[str, float]
    edge_penalties: dict[str, float]

    def __post_init__(self) -> None:
        if not self.edge_id:
            raise ValueError("edge_id cannot be empty")
        if not self.child_candidate_id:
            raise ValueError("child_candidate_id cannot be empty")
        if self.root and self.parent_candidate_id:
            raise ValueError("root edge must not carry parent_candidate_id")
        if not self.root and not self.parent_candidate_id:
            raise ValueError("non-root edge must carry parent_candidate_id")
        if self.hard_valid and self.hard_invalid_reasons:
            raise ValueError("hard_valid edge cannot have hard_invalid_reasons")


@dataclass(frozen=True, slots=True)
class GraphBuildDiagnostics:
    """Graph build statistics and pruning diagnostics."""

    graph_stats: dict[str, int]
    pruned_edges_by_reason: dict[str, int]
    ambiguous_tokens: tuple[str, ...]
    construction_warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateGraph:
    """Full parser_v2 candidate graph package."""

    node_candidates: tuple[ClauseNodeCandidate, ...]
    parent_edge_candidates: tuple[ParentEdgeCandidate, ...]
    diagnostics: GraphBuildDiagnostics


def candidate_graph_to_dict(graph: CandidateGraph) -> dict[str, object]:
    """Serialize graph to deterministic JSON-safe dict."""

    return {
        "node_candidates": [
            {
                "node_candidate_id": row.node_candidate_id,
                "token_id": row.token_id,
                "token_index": row.token_index,
                "level_type": row.level_type,
                "ordinal": row.ordinal,
                "depth_hint": row.depth_hint,
                "span_start": row.span_start,
                "span_end": row.span_end,
                "feature_vector": dict(sorted(row.feature_vector.items())),
            }
            for row in graph.node_candidates
        ],
        "parent_edge_candidates": [
            {
                "edge_id": row.edge_id,
                "child_candidate_id": row.child_candidate_id,
                "parent_candidate_id": row.parent_candidate_id,
                "root": row.root,
                "hard_valid": row.hard_valid,
                "hard_invalid_reasons": list(row.hard_invalid_reasons),
                "soft_score_components": dict(sorted(row.soft_score_components.items())),
                "edge_penalties": dict(sorted(row.edge_penalties.items())),
            }
            for row in graph.parent_edge_candidates
        ],
        "diagnostics": {
            "graph_stats": dict(sorted(graph.diagnostics.graph_stats.items())),
            "pruned_edges_by_reason": dict(
                sorted(graph.diagnostics.pruned_edges_by_reason.items()),
            ),
            "ambiguous_tokens": list(graph.diagnostics.ambiguous_tokens),
            "construction_warnings": list(graph.diagnostics.construction_warnings),
        },
    }
