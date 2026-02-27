"""Tests for parser_v2 solver MVP and status layer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.parser_v2.compare_v1 import compare_solver_vs_v1
from agent.parser_v2.solution_types import solution_to_dict
from agent.parser_v2.solver import solve_parser_v2


class TestParserV2Solver:
    def test_solver_accepts_simple_alpha_run(self) -> None:
        text = "(a) First.\n(b) Second.\n(c) Third.\n"
        solution = solve_parser_v2(text, section_key="sec::simple")
        assert solution.section_parse_status == "accepted"
        assert solution.abstained_token_ids == ()
        assert len(solution.selected_node_candidates) == 3
        assert len(solution.selected_parent_edges) == 3
        assert [node.clause_id for node in solution.nodes] == ["a", "b", "c"]
        assert all(node.parse_status == "accepted" for node in solution.nodes)

    def test_solver_abstains_ambiguous_case(self) -> None:
        text = (
            "(a) Parent clause.\n"
            "(i) Child one.\n"
            "(ii) Child two.\n"
            "subject to clause (i) above.\n"
        )
        solution = solve_parser_v2(text, section_key="sec::ambiguous")
        assert solution.section_parse_status == "abstain"
        assert solution.critical_node_abstain_ratio == 0.75
        assert "insufficient_context" in solution.section_reason_codes
        assert len(solution.abstained_token_ids) == 3
        assert [node.clause_id for node in solution.nodes] == ["a"]

    def test_solver_snapshot_v1(self) -> None:
        fixture_path = ROOT / "tests" / "fixtures" / "parser_v2" / "solver_snapshot_v1.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        solution = solve_parser_v2(
            payload["input_text"],
            section_key=payload["section_key"],
        )
        actual = solution_to_dict(solution)
        expected = payload["expected"]
        assert actual["section_parse_status"] == expected["section_parse_status"]
        assert actual["section_reason_codes"] == expected["section_reason_codes"]
        assert actual["critical_node_abstain_ratio"] == expected["critical_node_abstain_ratio"]
        assert actual["selected_node_candidates"] == expected["selected_node_candidates"]
        assert actual["selected_parent_edges"] == expected["selected_parent_edges"]
        assert actual["abstained_token_ids"] == expected["abstained_token_ids"]
        assert actual["objective_score"] == expected["objective_score"]
        assert actual["objective_components"] == expected["objective_components"]
        assert actual["top_k_alternatives"] == expected["top_k_alternatives"]
        assert actual["top1_score"] == expected["top1_score"]
        assert actual["top2_score"] == expected["top2_score"]
        assert actual["margin_abs"] == expected["margin_abs"]
        assert actual["margin_ratio"] == expected["margin_ratio"]

        projected_nodes = [
            {
                "node_candidate_id": row["node_candidate_id"],
                "clause_id": row["clause_id"],
                "parent_id": row["parent_id"],
                "depth": row["depth"],
                "level_type": row["level_type"],
                "parse_status": row["parse_status"],
                "abstain_reason_codes": row["abstain_reason_codes"],
                "solver_margin": row["solver_margin"],
                "confidence_score": row["confidence_score"],
            }
            for row in actual["nodes"]
        ]
        assert projected_nodes == expected["nodes"]


class TestParserV2CompareV1:
    def test_compare_solver_vs_v1_returns_expected_shape(self) -> None:
        text = "(a) First.\n(b) Second.\n(c) Third.\n"
        report = compare_solver_vs_v1(text, section_key="sec::compare")
        assert report["counts"]["v1_total_nodes"] == 3
        assert report["counts"]["v2_total_nodes"] == 3
        assert report["status"]["section_parse_status"] == "accepted"
        assert report["id_overlap"]["intersection_count"] == 3
        assert report["only_v1_clause_ids"] == []
        assert report["only_v2_clause_ids"] == []
