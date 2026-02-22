"""Tests for agent.clause_parser module."""
from agent.clause_parser import (
    ClauseNode,
    EnumeratorMatch,
    parse_clauses,
    resolve_path,
    scan_enumerators,
)


SAMPLE_CLAUSE_TEXT = """(a) the Borrower may incur Indebtedness; (b) any Subsidiary may incur Indebtedness; and (c) the total amount shall not exceed the limit."""


class TestScanEnumerators:
    def test_finds_alpha_enumerators(self) -> None:
        matches = scan_enumerators(SAMPLE_CLAUSE_TEXT)
        alpha_matches = [m for m in matches if m.level_type == "alpha"]
        assert len(alpha_matches) >= 3

    def test_match_attributes(self) -> None:
        matches = scan_enumerators(SAMPLE_CLAUSE_TEXT)
        assert all(isinstance(m, EnumeratorMatch) for m in matches)
        assert all(m.position >= 0 for m in matches)
        assert all(m.match_end > m.position for m in matches)

    def test_sorted_by_position(self) -> None:
        matches = scan_enumerators(SAMPLE_CLAUSE_TEXT)
        positions = [m.position for m in matches]
        assert positions == sorted(positions)


NESTED_CLAUSE_TEXT = """(a) General Basket. The Borrower may incur:
(i) secured Indebtedness in an aggregate principal amount not to exceed;
(ii) unsecured Indebtedness without limit; and
(iii) subordinated Indebtedness;
(b) Ratio Debt. The Borrower may incur Indebtedness if the leverage ratio."""


class TestParseClauses:
    def test_finds_clauses(self) -> None:
        nodes = parse_clauses(SAMPLE_CLAUSE_TEXT)
        assert len(nodes) >= 3

    def test_clause_node_types(self) -> None:
        nodes = parse_clauses(SAMPLE_CLAUSE_TEXT)
        assert all(isinstance(n, ClauseNode) for n in nodes)

    def test_global_offset(self) -> None:
        nodes_no_offset = parse_clauses(SAMPLE_CLAUSE_TEXT)
        nodes_with_offset = parse_clauses(SAMPLE_CLAUSE_TEXT, global_offset=1000)
        if nodes_no_offset and nodes_with_offset:
            assert nodes_with_offset[0].span_start == nodes_no_offset[0].span_start + 1000

    def test_nested_clauses(self) -> None:
        nodes = parse_clauses(NESTED_CLAUSE_TEXT)
        assert len(nodes) >= 5  # at least (a), (i), (ii), (iii), (b)
        # Check that some nodes have depth > 1
        depths = {n.depth for n in nodes}
        assert len(depths) >= 2  # at least two depth levels

    def test_structural_confidence(self) -> None:
        nodes = parse_clauses(NESTED_CLAUSE_TEXT)
        for n in nodes:
            assert 0.0 <= n.parse_confidence <= 1.0


class TestResolvePath:
    def test_resolve_simple(self) -> None:
        nodes = parse_clauses(SAMPLE_CLAUSE_TEXT)
        # Try to find node (a)
        result = resolve_path(nodes, ["(a)"])
        if result:
            assert "(a)" in result.label

    def test_resolve_nonexistent(self) -> None:
        nodes = parse_clauses(SAMPLE_CLAUSE_TEXT)
        result = resolve_path(nodes, ["(z)"])
        assert result is None
