"""Tests for parser_v2 candidate graph builder and parent edges."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.parser_v2.graph_builder import (
    build_candidate_graph,
    build_node_candidates,
    graph_diagnostics_report,
)
from agent.parser_v2.graph_types import candidate_graph_to_dict
from agent.parser_v2.lexer import lex_enumerator_tokens


_SAMPLE_TEXT = (
    "(a) Parent clause.\n"
    "(i) Child one.\n"
    "(ii) Child two.\n"
    "subject to clause (i) above.\n"
)


class TestParserV2NodeCandidates:
    def test_build_node_candidates_counts_and_ambiguity(self) -> None:
        _, tokens = lex_enumerator_tokens(_SAMPLE_TEXT)
        node_candidates, ambiguous_tokens, warnings = build_node_candidates(tokens)

        assert len(tokens) == 4
        assert len(node_candidates) == 7
        assert ambiguous_tokens == ["tok_00002_19", "tok_00003_34", "tok_00004_68"]
        assert warnings == []
        assert node_candidates[0].node_candidate_id == "nc_tok_00001_0_alpha"
        assert node_candidates[1].node_candidate_id == "nc_tok_00002_19_alpha"
        assert node_candidates[2].node_candidate_id == "nc_tok_00002_19_roman"

    def test_node_candidates_include_depth_and_feature_vectors(self) -> None:
        _, tokens = lex_enumerator_tokens(_SAMPLE_TEXT)
        node_candidates, _, _ = build_node_candidates(tokens)
        roman = next(row for row in node_candidates if row.node_candidate_id == "nc_tok_00003_34_roman")
        assert roman.depth_hint == 2
        assert roman.feature_vector["anchor"] is True
        assert roman.feature_vector["line_start"] is True
        assert isinstance(roman.feature_vector["indentation"], float)


class TestParserV2ParentEdges:
    def test_graph_default_edges_respect_hard_constraints(self) -> None:
        graph = build_candidate_graph(_SAMPLE_TEXT)
        nodes = {row.node_candidate_id: row for row in graph.node_candidates}
        edges = list(graph.parent_edge_candidates)

        # Every child has exactly one root edge.
        for child_id in nodes:
            root_edges = [row for row in edges if row.child_candidate_id == child_id and row.root]
            assert len(root_edges) == 1

        # Non-root edges are valid and strictly move to shallower depth.
        for edge in edges:
            if edge.root:
                continue
            assert edge.hard_valid is True
            assert edge.hard_invalid_reasons == ()
            parent = nodes[edge.parent_candidate_id]
            child = nodes[edge.child_candidate_id]
            assert parent.depth_hint < child.depth_hint
            assert parent.span_start < child.span_start

    def test_include_invalid_edges_exposes_pruned_reasons(self) -> None:
        graph = build_candidate_graph(_SAMPLE_TEXT, include_invalid_edges=True)
        invalid = [row for row in graph.parent_edge_candidates if not row.hard_valid]
        assert invalid
        reason_set = {reason for row in invalid for reason in row.hard_invalid_reasons}
        assert "depth_transition_invalid" in reason_set


class TestParserV2GraphDiagnostics:
    def test_candidate_graph_is_deterministic(self) -> None:
        first = build_candidate_graph(_SAMPLE_TEXT)
        second = build_candidate_graph(_SAMPLE_TEXT)
        assert candidate_graph_to_dict(first) == candidate_graph_to_dict(second)

    def test_graph_diagnostics_snapshot_v1(self) -> None:
        fixture_path = ROOT / "tests" / "fixtures" / "parser_v2" / "graph_diagnostics_snapshot_v1.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        graph = build_candidate_graph(payload["input_text"])
        assert graph_diagnostics_report(graph) == payload["expected_report"]
