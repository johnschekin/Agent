"""Parent edge candidate generation for parser_v2 candidate graphs."""

from __future__ import annotations

from collections import defaultdict

from agent.parser_v2.graph_types import ClauseNodeCandidate, ParentEdgeCandidate


def _root_edge_for_child(child: ClauseNodeCandidate) -> ParentEdgeCandidate:
    depth_penalty = max(0.0, float(child.depth_hint - 1) * 0.25)
    xref_penalty = 0.35 if bool(child.feature_vector.get("xref_preposition_pre")) else 0.0
    return ParentEdgeCandidate(
        edge_id=f"edge_root__{child.node_candidate_id}",
        child_candidate_id=child.node_candidate_id,
        parent_candidate_id="",
        root=True,
        hard_valid=True,
        hard_invalid_reasons=(),
        soft_score_components={
            "root_depth_preference": 1.0 if child.depth_hint == 1 else 0.2,
            "anchor_bonus": 1.0 if bool(child.feature_vector.get("anchor")) else 0.5,
            "ordinal_start_bonus": 1.0 if child.ordinal == 1 else 0.4,
        },
        edge_penalties={
            "depth_penalty": depth_penalty,
            "xref_penalty": xref_penalty,
        },
    )


def build_parent_edge_candidates(
    node_candidates: list[ClauseNodeCandidate],
    *,
    include_invalid_edges: bool = False,
    max_parent_candidates_per_child: int = 96,
) -> tuple[list[ParentEdgeCandidate], dict[str, int], list[str]]:
    """Build deterministic parent-edge candidates from node candidates.

    Returns:
    1. edge candidate list
    2. pruned-edge reason counts
    3. construction warnings
    """

    ordered = sorted(
        node_candidates,
        key=lambda row: (
            row.span_start,
            row.depth_hint,
            row.token_index,
            row.node_candidate_id,
        ),
    )
    by_id = {row.node_candidate_id: row for row in ordered}
    pruned_reason_counts: dict[str, int] = defaultdict(int)
    warnings: list[str] = []
    edges: list[ParentEdgeCandidate] = []

    for idx, child in enumerate(ordered):
        edges.append(_root_edge_for_child(child))
        considered = 0
        valid_non_root = 0

        for parent in reversed(ordered[:idx]):
            if considered >= max_parent_candidates_per_child:
                break
            considered += 1
            reasons: list[str] = []
            if parent.token_id == child.token_id:
                reasons.append("same_token_parent")
            if parent.span_start >= child.span_start:
                reasons.append("span_ordering_invalid")
            if parent.depth_hint >= child.depth_hint:
                reasons.append("depth_transition_invalid")

            hard_valid = not reasons
            if not hard_valid and not include_invalid_edges:
                for reason in reasons:
                    pruned_reason_counts[reason] += 1
                continue

            depth_step = max(1, child.depth_hint - parent.depth_hint)
            xref_penalty = 0.35 if bool(child.feature_vector.get("xref_preposition_pre")) else 0.0
            edge = ParentEdgeCandidate(
                edge_id=f"edge_{parent.node_candidate_id}__{child.node_candidate_id}",
                child_candidate_id=child.node_candidate_id,
                parent_candidate_id=parent.node_candidate_id,
                root=False,
                hard_valid=hard_valid,
                hard_invalid_reasons=tuple(reasons),
                soft_score_components={
                    "depth_transition": 1.0 if depth_step == 1 else max(0.0, 1.0 - 0.25 * (depth_step - 1)),
                    "anchor_compatibility": 1.0
                    if bool(parent.feature_vector.get("anchor")) and bool(child.feature_vector.get("anchor"))
                    else 0.6,
                    "ordinal_proximity": 1.0
                    if (child.ordinal >= parent.ordinal and child.depth_hint == parent.depth_hint + 1)
                    else 0.6,
                },
                edge_penalties={
                    "depth_gap_penalty": max(0.0, float(depth_step - 1) * 0.25),
                    "xref_penalty": xref_penalty,
                },
            )
            edges.append(edge)
            if hard_valid:
                valid_non_root += 1

        if child.depth_hint > 1 and valid_non_root == 0:
            warnings.append(
                f"child_without_non_root_parent:{child.node_candidate_id}:depth={child.depth_hint}",
            )

    # Invariant check: every edge references known node IDs.
    for edge in edges:
        if edge.child_candidate_id not in by_id:
            raise ValueError(f"Edge references unknown child candidate: {edge.child_candidate_id}")
        if not edge.root and edge.parent_candidate_id not in by_id:
            raise ValueError(f"Edge references unknown parent candidate: {edge.parent_candidate_id}")

    return edges, dict(pruned_reason_counts), warnings
