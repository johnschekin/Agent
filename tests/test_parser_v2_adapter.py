"""Tests for parser_v2 adapter to legacy clause/link contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.parser_v2.adapter import (
    adapt_solution_to_legacy_clause_nodes,
    build_link_contract_payload,
)
from agent.parser_v2.graph_builder import build_candidate_graph
from agent.parser_v2.solver import solve_candidate_graph


def test_adapter_emits_legacy_fields() -> None:
    text = "(a) First.\n(b) Second.\n(c) Third.\n"
    graph = build_candidate_graph(text)
    solution = solve_candidate_graph(graph, section_key="sec::adapter")
    rows = adapt_solution_to_legacy_clause_nodes(solution, graph, text, global_offset=100)
    assert len(rows) == 3
    first = rows[0]
    expected_keys = {
        "id",
        "label",
        "depth",
        "level_type",
        "span_start",
        "span_end",
        "header_text",
        "parent_id",
        "children_ids",
        "anchor_ok",
        "run_length_ok",
        "gap_ok",
        "indentation_score",
        "xref_suspected",
        "is_structural_candidate",
        "parse_confidence",
        "demotion_reason",
        "parse_status",
        "abstain_reason_codes",
        "solver_margin",
    }
    assert expected_keys.issubset(first.keys())
    assert first["span_start"] >= 100
    assert first["parse_status"] == "accepted"


def test_build_link_contract_payload_contains_section_status() -> None:
    text = "(a) Parent.\n(i) Child.\n(ii) Child two.\nsubject to clause (i) above.\n"
    graph = build_candidate_graph(text)
    solution = solve_candidate_graph(graph, section_key="sec::adapter_status")
    payload = build_link_contract_payload(solution, graph, text, global_offset=0)
    assert payload["section_parse_status"] in {"accepted", "review", "abstain"}
    assert isinstance(payload["section_reason_codes"], tuple)
    assert isinstance(payload["nodes"], list)
