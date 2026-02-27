"""Invariant checks for clause tree integrity.

These tests validate tree-shape guarantees independently from edge-case totals.
"""
from __future__ import annotations

from collections import defaultdict

import pytest

from agent.clause_parser import ClauseNode, parse_clauses


TEST_TEXTS = [
    # Straightforward root alpha run.
    "(a) First.\n(b) Second.\n(c) Third.\n",
    # Canonical nested sequence.
    (
        "(a) Parent.\n"
        "(i) Child one.\n"
        "(ii) Child two.\n"
        "(A) Grandchild.\n"
        "(1) Great grandchild.\n"
        "(b) Next parent.\n"
    ),
    # Mixed inline/xref-like content.
    (
        "(a) Borrower may request commitments, provided that "
        "(i) no default exists and (ii) reps are true; "
        "(x) additional condition and (y) lender consent applies.\n"
        "(b) Procedures.\n"
    ),
    # Repeated labels to ensure duplicate ids still satisfy linkage invariants.
    "(a) First.\n(a) Duplicate.\n(a) Third duplicate.\n(b) Distinct.\n",
]


def _segment_count(path_id: str) -> int:
    return len([part for part in str(path_id).split(".") if part])


def _assert_tree_invariants(nodes: list[ClauseNode]) -> None:
    by_id = {node.id: node for node in nodes}

    # 1) Parent links are valid and path-format coherent.
    for node in nodes:
        assert node.id, "node id must be non-empty"
        assert node.span_start < node.span_end, (
            f"Invalid span for {node.id}: {node.span_start} !< {node.span_end}"
        )
        assert node.parent_id != node.id, f"Node cannot parent itself: {node.id}"

        if node.parent_id:
            assert node.parent_id in by_id, (
                f"Missing parent for {node.id}: {node.parent_id}"
            )
            assert node.id.startswith(f"{node.parent_id}."), (
                f"Path mismatch: child={node.id} parent={node.parent_id}"
            )

    # 2) Child registrations are reciprocal and target existing nodes.
    for node in nodes:
        for child_id in node.children_ids:
            assert child_id in by_id, (
                f"Parent {node.id} references missing child {child_id}"
            )
            assert by_id[child_id].parent_id == node.id, (
                f"Reciprocity failure: {child_id}.parent_id={by_id[child_id].parent_id} "
                f"expected {node.id}"
            )

    # 3) Parent segment count is exactly one less than child segment count.
    for node in nodes:
        child_segments = _segment_count(node.id)
        if node.parent_id:
            parent_segments = _segment_count(node.parent_id)
            assert child_segments == parent_segments + 1, (
                f"Segment mismatch: child={node.id} ({child_segments}) "
                f"parent={node.parent_id} ({parent_segments})"
            )
        else:
            assert child_segments == 1, (
                f"Root node should have single segment id: {node.id}"
            )

    # 4) Sibling intervals do not cross.
    siblings: dict[str, list[ClauseNode]] = defaultdict(list)
    for node in nodes:
        siblings[node.parent_id].append(node)

    for parent_id, group in siblings.items():
        ordered = sorted(group, key=lambda item: item.span_start)
        for i in range(1, len(ordered)):
            prev = ordered[i - 1]
            curr = ordered[i]
            assert prev.span_end <= curr.span_start, (
                "Sibling span overlap/crossing detected for parent "
                f"{parent_id!r}: {prev.id}({prev.span_start},{prev.span_end}) "
                f"vs {curr.id}({curr.span_start},{curr.span_end})"
            )


@pytest.mark.parametrize("text", TEST_TEXTS)
def test_clause_tree_invariants_hold(text: str) -> None:
    nodes = parse_clauses(text)
    assert nodes, "Expected parse_clauses to return nodes for invariant sample"
    _assert_tree_invariants(nodes)


def test_invariants_hold_for_nested_resolve_path_shape() -> None:
    text = (
        "(a) Parent.\n"
        "(i) Child one.\n"
        "(ii) Child two.\n"
        "(A) Cap child.\n"
        "(1) Numeric child.\n"
        "(2) Numeric sibling.\n"
    )
    nodes = parse_clauses(text)
    _assert_tree_invariants(nodes)
