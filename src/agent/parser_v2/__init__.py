"""Parser v2 foundations: normalization and lexer contracts."""

from agent.parser_v2.graph_builder import (
    build_candidate_graph,
    build_node_candidates,
    graph_diagnostics_report,
)
from agent.parser_v2.adapter import (
    adapt_solution_to_legacy_clause_nodes,
    build_link_contract_payload,
)
from agent.parser_v2.compare_v1 import compare_solver_vs_v1
from agent.parser_v2.dual_run import run_dual_run
from agent.parser_v2.graph_types import (
    CandidateGraph,
    ClauseNodeCandidate,
    GraphBuildDiagnostics,
    ParentEdgeCandidate,
    candidate_graph_to_dict,
)
from agent.parser_v2.lexer import lex_enumerator_tokens
from agent.parser_v2.normalization import normalize_for_parser_v2
from agent.parser_v2.solution_types import (
    ParseStatus,
    SolvedClauseNode,
    SolverSolution,
    solution_to_dict,
)
from agent.parser_v2.solver import solve_candidate_graph, solve_parser_v2
from agent.parser_v2.types import (
    CandidateType,
    LexerToken,
    NormalizedText,
    SourceSpan,
)

__all__ = [
    "CandidateGraph",
    "CandidateType",
    "ClauseNodeCandidate",
    "GraphBuildDiagnostics",
    "LexerToken",
    "NormalizedText",
    "ParseStatus",
    "ParentEdgeCandidate",
    "SolvedClauseNode",
    "SourceSpan",
    "SolverSolution",
    "adapt_solution_to_legacy_clause_nodes",
    "build_candidate_graph",
    "build_link_contract_payload",
    "build_node_candidates",
    "candidate_graph_to_dict",
    "compare_solver_vs_v1",
    "graph_diagnostics_report",
    "lex_enumerator_tokens",
    "normalize_for_parser_v2",
    "run_dual_run",
    "solution_to_dict",
    "solve_candidate_graph",
    "solve_parser_v2",
]
