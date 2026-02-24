"""Tests for definition dependency graph analytics."""

from agent.definition_graph import build_definition_dependency_graph, dependency_overlap


def test_dependency_overlap() -> None:
    text = "This means the amount of Consolidated EBITDA and Total Debt."
    overlap = dependency_overlap(text, ["Consolidated EBITDA", "Total Debt", "Lien"])
    assert 0.0 < overlap < 1.0


def test_build_definition_dependency_graph() -> None:
    definitions = [
        {
            "term": "Permitted Debt",
            "definition_text": '"Permitted Debt" means debt permitted by "Credit Agreement".',
        },
        {
            "term": "Credit Agreement",
            "definition_text": '"Credit Agreement" means this Agreement.',
        },
    ]
    graph = build_definition_dependency_graph(definitions)
    summary = graph["summary"]
    assert summary["node_count"] == 2
    assert summary["edge_count"] >= 1

