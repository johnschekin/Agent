"""Deterministic solver MVP and status layer for parser_v2."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter

from agent.parser_v2.graph_builder import build_candidate_graph
from agent.parser_v2.graph_types import CandidateGraph, ClauseNodeCandidate, ParentEdgeCandidate
from agent.parser_v2.lexer import lex_enumerator_tokens
from agent.parser_v2.solution_types import ParseStatus, SolvedClauseNode, SolverSolution
from agent.parser_v2.types import LexerToken, NormalizedText


_DEFAULT_PARSER_VERSION = "parser_v2_solver_v1"
_ABSTAIN_MARGIN_THRESHOLD = 0.08
_REVIEW_MARGIN_THRESHOLD = 0.20
_SECTION_ABSTAIN_RATIO_THRESHOLD = 0.40


@dataclass(slots=True)
class _TokenDecision:
    token_id: str
    selected: ClauseNodeCandidate | None
    status: ParseStatus
    reason_codes: tuple[str, ...]
    margin_abs: float
    confidence_score: float
    alternatives: tuple[tuple[str, float], ...]


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _node_score(node: ClauseNodeCandidate) -> float:
    feature = node.feature_vector
    anchor = 0.35 if bool(feature.get("anchor")) else 0.0
    line_start = 0.20 if bool(feature.get("line_start")) else 0.0
    indentation = 0.10 * float(feature.get("indentation", 0.0) or 0.0)
    depth_bias = 0.15 if node.depth_hint == 1 else 0.08
    xref_keyword_penalty = 0.12 if bool(feature.get("xref_keyword_pre")) else 0.0
    xref_preposition_penalty = 0.20 if bool(feature.get("xref_preposition_pre")) else 0.0
    raw = anchor + line_start + depth_bias + indentation - xref_keyword_penalty - xref_preposition_penalty
    return round(_clamp01(raw), 6)


def _edge_score(edge: ParentEdgeCandidate) -> float:
    positive = sum(float(v) for v in edge.soft_score_components.values())
    penalties = sum(float(v) for v in edge.edge_penalties.values())
    return round(positive - penalties, 6)


def _choose_token_decisions(
    graph: CandidateGraph,
    *,
    abstain_margin_threshold: float,
    review_margin_threshold: float,
) -> tuple[list[_TokenDecision], list[str]]:
    by_token: dict[str, list[ClauseNodeCandidate]] = defaultdict(list)
    for node in graph.node_candidates:
        by_token[node.token_id].append(node)

    warnings: list[str] = []
    decisions: list[_TokenDecision] = []
    ordered_token_ids = sorted(
        by_token.keys(),
        key=lambda token_id: min(
            row.token_index for row in by_token[token_id]
        ),
    )

    for token_id in ordered_token_ids:
        candidates = by_token[token_id]
        ranked = sorted(
            ((_node_score(row), row) for row in candidates),
            key=lambda item: (
                -item[0],
                item[1].depth_hint,
                item[1].node_candidate_id,
            ),
        )
        top1_score, top1 = ranked[0]
        top2_score = ranked[1][0] if len(ranked) > 1 else max(0.0, top1_score - 0.3)
        margin_abs = round(max(0.0, top1_score - top2_score), 6)
        reasons: list[str] = []

        if top1_score < 0.12 or margin_abs < abstain_margin_threshold:
            status: ParseStatus = "abstain"
            reasons.append("low_margin")
            if bool(top1.feature_vector.get("xref_preposition_pre")):
                reasons.append("xref_conflict")
            selected = None
            confidence = round(top1_score, 6)
        else:
            selected = top1
            confidence = round(top1_score, 6)
            if margin_abs < review_margin_threshold:
                status = "review"
                reasons.append("low_margin")
            elif bool(top1.feature_vector.get("xref_preposition_pre")):
                status = "review"
                reasons.append("xref_conflict")
            elif not bool(top1.feature_vector.get("anchor")):
                status = "review"
                reasons.append("layout_uncertain")
            else:
                status = "accepted"

        decisions.append(
            _TokenDecision(
                token_id=token_id,
                selected=selected,
                status=status,
                reason_codes=tuple(sorted(set(reasons))),
                margin_abs=margin_abs,
                confidence_score=confidence,
                alternatives=tuple(
                    (row.node_candidate_id, score)
                    for score, row in ranked[:2]
                ),
            ),
        )
        if len(candidates) > 1 and status == "abstain":
            warnings.append(f"ambiguous_abstain:{token_id}")

    return decisions, warnings


def _choose_parent_edges(
    graph: CandidateGraph,
    selected_candidates: dict[str, ClauseNodeCandidate],
) -> tuple[list[ParentEdgeCandidate], list[str], float]:
    edges_by_child: dict[str, list[ParentEdgeCandidate]] = defaultdict(list)
    for edge in graph.parent_edge_candidates:
        edges_by_child[edge.child_candidate_id].append(edge)

    warnings: list[str] = []
    selected_edges: list[ParentEdgeCandidate] = []
    edge_total = 0.0

    ordered_children = sorted(
        selected_candidates.values(),
        key=lambda row: (
            row.span_start,
            row.span_end,
            row.depth_hint,
            row.node_candidate_id,
        ),
    )
    selected_ids = set(selected_candidates.keys())

    for child in ordered_children:
        candidate_edges = []
        for edge in edges_by_child.get(child.node_candidate_id, []):
            if not edge.hard_valid:
                continue
            if not edge.root and edge.parent_candidate_id not in selected_ids:
                continue
            candidate_edges.append(edge)

        if not candidate_edges:
            warnings.append(f"parent_conflict:{child.node_candidate_id}")
            continue

        ranked = sorted(
            ((_edge_score(edge), edge) for edge in candidate_edges),
            key=lambda item: (
                -item[0],
                1 if item[1].root else 0,  # prefer non-root when scores tie
                item[1].edge_id,
            ),
        )
        _, chosen = ranked[0]
        selected_edges.append(chosen)
        edge_total += _edge_score(chosen)

    return selected_edges, warnings, round(edge_total, 6)


def _build_solved_nodes(
    selected_candidates: dict[str, ClauseNodeCandidate],
    selected_edges: list[ParentEdgeCandidate],
    decisions_by_token: dict[str, _TokenDecision],
) -> list[SolvedClauseNode]:
    by_id = selected_candidates
    parent_candidate_by_child: dict[str, str] = {}
    children_by_parent: dict[str, list[str]] = defaultdict(list)
    root_children: list[str] = []
    for edge in selected_edges:
        if edge.root:
            root_children.append(edge.child_candidate_id)
            continue
        parent_candidate_by_child[edge.child_candidate_id] = edge.parent_candidate_id
        children_by_parent[edge.parent_candidate_id].append(edge.child_candidate_id)

    root_children.sort(key=lambda node_id: (by_id[node_id].span_start, by_id[node_id].node_candidate_id))
    for parent_id, children in children_by_parent.items():
        children.sort(key=lambda node_id: (by_id[node_id].span_start, by_id[node_id].node_candidate_id))

    nodes_out: list[SolvedClauseNode] = []
    clause_id_by_candidate: dict[str, str] = {}
    suffix_counter_by_parent: dict[str, dict[str, int]] = defaultdict(dict)

    def emit_subtree(candidate_id: str, parent_clause_id: str, depth: int) -> None:
        candidate = by_id[candidate_id]
        token_decision = decisions_by_token[candidate.token_id]
        sibling_counter = suffix_counter_by_parent[parent_clause_id]
        base = candidate.normalized_label
        index = sibling_counter.get(base, 0) + 1
        sibling_counter[base] = index
        segment = base if index == 1 else f"{base}_{index}"
        clause_id = segment if not parent_clause_id else f"{parent_clause_id}.{segment}"
        clause_id_by_candidate[candidate_id] = clause_id
        reason_codes = token_decision.reason_codes if token_decision.status != "accepted" else ()
        nodes_out.append(
            SolvedClauseNode(
                node_candidate_id=candidate.node_candidate_id,
                clause_id=clause_id,
                parent_id=parent_clause_id,
                depth=depth,
                level_type=candidate.level_type,
                span_start=candidate.span_start,
                span_end=candidate.span_end,
                is_structural_candidate=token_decision.status != "abstain",
                xref_suspected=bool(
                    candidate.feature_vector.get("xref_keyword_pre")
                    or candidate.feature_vector.get("xref_preposition_pre")
                ),
                parse_status=token_decision.status,
                abstain_reason_codes=reason_codes,
                solver_margin=token_decision.margin_abs,
                confidence_score=token_decision.confidence_score,
            ),
        )
        for child_id in children_by_parent.get(candidate_id, []):
            emit_subtree(child_id, clause_id, depth + 1)

    for child_id in root_children:
        emit_subtree(child_id, "", 1)

    nodes_out.sort(key=lambda row: (row.span_start, row.clause_id))
    return nodes_out


def _build_parse_run_id(section_key: str, selected_node_ids: list[str], abstained_tokens: list[str]) -> str:
    payload = "|".join([section_key, *sorted(selected_node_ids), *sorted(abstained_tokens)])
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]  # noqa: S324 - non-crypto id
    return f"p2_{digest}"


def solve_candidate_graph(
    graph: CandidateGraph,
    *,
    section_key: str = "section::unknown",
    parser_version: str = _DEFAULT_PARSER_VERSION,
    abstain_margin_threshold: float = _ABSTAIN_MARGIN_THRESHOLD,
    review_margin_threshold: float = _REVIEW_MARGIN_THRESHOLD,
    section_abstain_ratio_threshold: float = _SECTION_ABSTAIN_RATIO_THRESHOLD,
) -> SolverSolution:
    """Solve candidate graph with deterministic scoring and abstain policy."""

    started = perf_counter()
    decisions, decision_warnings = _choose_token_decisions(
        graph,
        abstain_margin_threshold=abstain_margin_threshold,
        review_margin_threshold=review_margin_threshold,
    )
    selected_candidates = {
        decision.selected.node_candidate_id: decision.selected
        for decision in decisions
        if decision.selected is not None
    }
    selected_edges, edge_warnings, edge_score_total = _choose_parent_edges(
        graph,
        selected_candidates,
    )
    decisions_by_token = {decision.token_id: decision for decision in decisions}
    solved_nodes = _build_solved_nodes(selected_candidates, selected_edges, decisions_by_token)

    selected_node_ids = sorted(selected_candidates.keys())
    selected_edge_ids = sorted(row.edge_id for row in selected_edges)
    abstained_token_ids = sorted(
        decision.token_id for decision in decisions if decision.status == "abstain"
    )
    node_score_total = round(
        sum(decision.confidence_score for decision in decisions if decision.selected is not None),
        6,
    )
    objective_score = round(node_score_total + edge_score_total, 6)
    margins = [decision.margin_abs for decision in decisions] or [0.0]
    avg_margin = round(sum(margins) / len(margins), 6)
    top1_score = objective_score
    top2_score = round(max(0.0, objective_score - avg_margin), 6)
    margin_abs = round(max(0.0, top1_score - top2_score), 6)
    margin_ratio = round((margin_abs / top1_score) if top1_score > 0 else 0.0, 6)

    top_k_alternatives: list[dict[str, object]] = []
    for decision in decisions:
        for rank, (candidate_id, score) in enumerate(decision.alternatives, start=1):
            top_k_alternatives.append(
                {
                    "token_id": decision.token_id,
                    "rank": rank,
                    "node_candidate_id": candidate_id,
                    "score": score,
                    "selected": bool(
                        decision.selected is not None
                        and decision.selected.node_candidate_id == candidate_id
                    ),
                },
            )

    total_tokens = max(1, len(decisions))
    critical_node_abstain_ratio = round(len(abstained_token_ids) / total_tokens, 6)
    section_reasons: set[str] = set()
    for decision in decisions:
        section_reasons.update(decision.reason_codes)
    if edge_warnings:
        section_reasons.add("parent_conflict")

    if critical_node_abstain_ratio >= section_abstain_ratio_threshold:
        section_status: ParseStatus = "abstain"
        section_reasons.add("insufficient_context")
    elif any(decision.status == "review" for decision in decisions) or abstained_token_ids:
        section_status = "review"
    else:
        section_status = "accepted"

    parse_run_id = _build_parse_run_id(section_key, selected_node_ids, abstained_token_ids)
    duration_ms = round((perf_counter() - started) * 1000, 3)
    solver_diagnostics = {
        "runtime_ms": duration_ms,
        "input_node_candidates": len(graph.node_candidates),
        "input_edge_candidates": len(graph.parent_edge_candidates),
        "selected_nodes": len(selected_node_ids),
        "selected_edges": len(selected_edge_ids),
        "warnings": sorted(set([*decision_warnings, *edge_warnings])),
    }

    return SolverSolution(
        parse_run_id=parse_run_id,
        parser_version=parser_version,
        section_key=section_key,
        selected_node_candidates=tuple(selected_node_ids),
        selected_parent_edges=tuple(selected_edge_ids),
        abstained_token_ids=tuple(abstained_token_ids),
        objective_score=objective_score,
        objective_components={
            "node_score_total": node_score_total,
            "edge_score_total": edge_score_total,
            "margin_abs_avg": avg_margin,
        },
        top_k_alternatives=tuple(
            sorted(
                top_k_alternatives,
                key=lambda row: (
                    str(row["token_id"]),
                    int(row["rank"]),
                    str(row["node_candidate_id"]),
                ),
            ),
        ),
        solver_diagnostics=solver_diagnostics,
        nodes=tuple(solved_nodes),
        section_parse_status=section_status,
        section_reason_codes=tuple(sorted(section_reasons)),
        critical_node_abstain_ratio=critical_node_abstain_ratio,
        top1_score=top1_score,
        top2_score=top2_score,
        margin_abs=margin_abs,
        margin_ratio=margin_ratio,
    )


def solve_parser_v2(
    payload: str | NormalizedText | list[LexerToken] | CandidateGraph,
    *,
    section_key: str = "section::unknown",
) -> SolverSolution:
    """High-level parser_v2 solve entrypoint."""

    if isinstance(payload, CandidateGraph):
        graph = payload
    else:
        graph = build_candidate_graph(payload)
        if section_key == "section::unknown" and not isinstance(payload, list):
            if isinstance(payload, str):
                section_key = f"text::{len(payload)}"
            else:
                section_key = f"normalized::{len(payload.normalized_text)}"
    return solve_candidate_graph(graph, section_key=section_key)
