"""Candidate graph builder for parser_v2."""

from __future__ import annotations

from agent.enumerator import CANONICAL_DEPTH
from agent.parser_v2.graph_edges import build_parent_edge_candidates
from agent.parser_v2.graph_types import (
    CandidateGraph,
    ClauseNodeCandidate,
    GraphBuildDiagnostics,
    candidate_graph_to_dict,
)
from agent.parser_v2.lexer import lex_enumerator_tokens
from agent.parser_v2.types import CandidateType, LexerToken, NormalizedText


def build_node_candidates(tokens: list[LexerToken]) -> tuple[list[ClauseNodeCandidate], list[str], list[str]]:
    """Build deterministic node candidates from lexer tokens.

    Returns:
    1. node candidates
    2. ambiguous token IDs
    3. construction warnings
    """

    ordered_tokens = sorted(
        tokens,
        key=lambda row: (
            row.position_start,
            row.position_end,
            row.raw_label,
            row.token_id,
        ),
    )
    warnings: list[str] = []
    ambiguous_tokens: list[str] = []
    node_candidates: list[ClauseNodeCandidate] = []

    for token_index, token in enumerate(ordered_tokens):
        if len(token.candidate_types) > 1:
            ambiguous_tokens.append(token.token_id)
        for level_type in token.candidate_types:
            ordinal = int(token.ordinal_by_type.get(level_type, -1))
            depth_hint = int(CANONICAL_DEPTH.get(level_type, 0))
            if ordinal <= 0:
                warnings.append(
                    f"missing_ordinal:{token.token_id}:{level_type}",
                )
                continue
            if depth_hint <= 0:
                warnings.append(
                    f"unknown_depth:{token.token_id}:{level_type}",
                )
                continue
            node_candidates.append(
                ClauseNodeCandidate(
                    node_candidate_id=f"nc_{token.token_id}_{level_type}",
                    token_id=token.token_id,
                    token_index=token_index,
                    level_type=level_type,
                    ordinal=ordinal,
                    depth_hint=depth_hint,
                    span_start=token.position_start,
                    span_end=token.position_end,
                    feature_vector={
                        "anchor": bool(token.layout_features.get("anchored_boundary", False)),
                        "line_start": bool(token.is_line_start),
                        "indentation": float(token.indentation_score),
                        "xref_keyword_pre": bool(token.xref_context_features.get("xref_keyword_pre", False)),
                        "xref_keyword_post": bool(token.xref_context_features.get("xref_keyword_post", False)),
                        "xref_preposition_pre": bool(
                            token.xref_context_features.get("xref_preposition_pre", False),
                        ),
                    },
                ),
            )

    node_candidates.sort(
        key=lambda row: (
            row.span_start,
            row.span_end,
            row.depth_hint,
            row.node_candidate_id,
        ),
    )
    return node_candidates, sorted(set(ambiguous_tokens)), warnings


def build_candidate_graph(
    payload: str | NormalizedText | list[LexerToken],
    *,
    include_invalid_edges: bool = False,
    max_parent_candidates_per_child: int = 96,
) -> CandidateGraph:
    """Build parser_v2 candidate graph from text or tokens."""

    tokens: list[LexerToken]
    if isinstance(payload, list):
        tokens = payload
    else:
        _, tokens = lex_enumerator_tokens(payload)

    node_candidates, ambiguous_tokens, node_warnings = build_node_candidates(tokens)
    edges, pruned_reason_counts, edge_warnings = build_parent_edge_candidates(
        node_candidates,
        include_invalid_edges=include_invalid_edges,
        max_parent_candidates_per_child=max_parent_candidates_per_child,
    )
    root_edges = sum(1 for row in edges if row.root)
    non_root_edges = len(edges) - root_edges

    diagnostics = GraphBuildDiagnostics(
        graph_stats={
            "token_count": len(tokens),
            "node_candidate_count": len(node_candidates),
            "edge_candidate_count": len(edges),
            "root_edge_count": root_edges,
            "non_root_edge_count": non_root_edges,
            "ambiguous_token_count": len(ambiguous_tokens),
        },
        pruned_edges_by_reason=dict(sorted(pruned_reason_counts.items())),
        ambiguous_tokens=tuple(sorted(ambiguous_tokens)),
        construction_warnings=tuple(sorted(set([*node_warnings, *edge_warnings]))),
    )
    return CandidateGraph(
        node_candidates=tuple(node_candidates),
        parent_edge_candidates=tuple(edges),
        diagnostics=diagnostics,
    )


def graph_diagnostics_report(graph: CandidateGraph) -> dict[str, object]:
    """Return deterministic diagnostics dump for tests/reporting."""

    payload = candidate_graph_to_dict(graph)
    return {
        "graph_stats": payload["diagnostics"]["graph_stats"],
        "pruned_edges_by_reason": payload["diagnostics"]["pruned_edges_by_reason"],
        "ambiguous_tokens": payload["diagnostics"]["ambiguous_tokens"],
        "construction_warnings": payload["diagnostics"]["construction_warnings"],
    }
