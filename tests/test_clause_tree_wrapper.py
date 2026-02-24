"""Tests for ClauseTree wrapper API."""

from agent.clause_parser import ClauseTree, parse_clause_tree


SAMPLE = """
(a) The Borrower shall not incur debt.
(b) The Borrower may incur Permitted Debt.
    (i) ratio debt.
    (ii) acquisition debt.
"""


def test_clause_tree_from_text() -> None:
    tree = ClauseTree.from_text(SAMPLE)
    assert tree.nodes
    assert tree.roots


def test_clause_tree_resolve_path() -> None:
    tree = parse_clause_tree(SAMPLE)
    node = tree.resolve(["(b)", "(i)"])
    assert node is not None
    assert node.label.lower().startswith("(i")

