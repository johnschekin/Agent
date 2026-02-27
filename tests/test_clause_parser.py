"""Tests for agent.clause_parser module.

Covers all 6 improvement phases:
  Phase 0: Consolidation onto enumerator.py
  Phase 1: Inline disambiguation (last_sibling_at_level)
  Phase 2: Enhanced xref detection
  Phase 3: 5-signal confidence scoring
  Phase 4: Ghost clause filtering
  Phase 5: Schema alignment (indentation_score, xref_suspected)
  Phase 6: Inline enumeration detection
"""

from agent.clause_parser import (
    ClauseNode,
    ClauseTree,
    EnumeratorMatch,
    parse_clauses,
    resolve_path,
    scan_enumerators,
)

# ===========================================================================
# Phase 0: Basic scanning and consolidation
# ===========================================================================

SAMPLE_CLAUSE_TEXT = (
    "(a) the Borrower may incur Indebtedness; "
    "(b) any Subsidiary may incur Indebtedness; "
    "and (c) the total amount shall not exceed the limit."
)


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
        depths = {n.depth for n in nodes}
        assert len(depths) >= 2

    def test_structural_confidence(self) -> None:
        nodes = parse_clauses(NESTED_CLAUSE_TEXT)
        for n in nodes:
            assert 0.0 <= n.parse_confidence <= 1.0


class TestResolvePath:
    def test_resolve_simple(self) -> None:
        nodes = parse_clauses(SAMPLE_CLAUSE_TEXT)
        result = resolve_path(nodes, ["(a)"])
        if result:
            assert "(a)" in result.label

    def test_resolve_nonexistent(self) -> None:
        nodes = parse_clauses(SAMPLE_CLAUSE_TEXT)
        result = resolve_path(nodes, ["(z)"])
        assert result is None


# ===========================================================================
# Phase 1: Inline disambiguation
# ===========================================================================


class TestInlineDisambiguation:
    def test_i_as_alpha_after_h(self) -> None:
        """(i) after (a)...(h) should be classified as alpha (ordinal 9)."""
        text = (
            "(a) First.\n(b) Second.\n(c) Third.\n(d) Fourth.\n"
            "(e) Fifth.\n(f) Sixth.\n(g) Seventh.\n(h) Eighth.\n"
            "(i) Ninth item.\n(j) Tenth item.\n"
        )
        nodes = parse_clauses(text)
        node_i = next(
            (n for n in nodes
             if "i" in n.id.split(".")[-1]
             and n.label.strip("()").strip() == "i"),
            None,
        )
        assert node_i is not None
        assert node_i.level_type == "alpha"
        assert node_i.depth == 1  # same level as (a)-(h)

    def test_i_as_roman_under_alpha(self) -> None:
        """(i) under (a) with (ii) following should be roman."""
        text = (
            "(a) General Basket. The Borrower may incur:\n"
            "(i) secured Indebtedness;\n"
            "(ii) unsecured Indebtedness;\n"
            "(iii) subordinated Indebtedness;\n"
        )
        nodes = parse_clauses(text)
        node_i = next(
            (n for n in nodes if n.label.strip().strip("()").strip() == "i"),
            None,
        )
        assert node_i is not None
        assert node_i.level_type == "roman"
        assert node_i.depth == 2  # child of (a)

    def test_v_as_roman_in_roman_run(self) -> None:
        """(v) in (iv)(v)(vi) should be roman."""
        text = (
            "(a) Parent clause:\n"
            "(iv) fourth item;\n"
            "(v) fifth item;\n"
            "(vi) sixth item;\n"
        )
        nodes = parse_clauses(text)
        node_v = next(
            (n for n in nodes if n.label.strip().strip("()").strip() == "v"),
            None,
        )
        assert node_v is not None
        assert node_v.level_type == "roman"

    def test_v_as_alpha_after_u(self) -> None:
        """(v) after (t)(u) should be alpha."""
        text = (
            "(t) item t.\n(u) item u.\n(v) item v.\n(w) item w.\n"
        )
        nodes = parse_clauses(text)
        node_v = next(
            (n for n in nodes if n.label.strip().strip("()").strip() == "v"),
            None,
        )
        assert node_v is not None
        assert node_v.level_type == "alpha"

    def test_level_reset_between_parents(self) -> None:
        """(b)'s (i) should start fresh, not contaminated by (a)'s children."""
        text = (
            "(a) First parent:\n"
            "(i) first child;\n"
            "(ii) second child;\n"
            "(b) Second parent:\n"
            "(i) first child of b;\n"
            "(ii) second child of b;\n"
        )
        nodes = parse_clauses(text)
        # Both (i)s under (a) and (b) should be roman
        roman_nodes = [n for n in nodes if n.level_type == "roman"]
        assert len(roman_nodes) >= 4  # (i),(ii) under (a) and (i),(ii) under (b)

        # Check (b)'s children
        node_b = next((n for n in nodes if n.id == "b"), None)
        assert node_b is not None
        b_children = [n for n in nodes if n.parent_id == "b"]
        assert len(b_children) >= 2

    def test_mixed_alpha_roman_same_doc(self) -> None:
        """Same doc can have both alpha (i) and roman (i) in different sections."""
        text = (
            "(a) First.\n(b) Second.\n(c) Third.\n(d) Fourth.\n"
            "(e) Fifth.\n(f) Sixth.\n(g) Seventh.\n(h) Eighth.\n"
            "(i) Ninth as alpha.\n(j) Tenth as alpha.\n"
        )
        nodes = parse_clauses(text)
        # (i) should be alpha since it continues (a)-(h) sequence
        node_i = next(
            (n for n in nodes if n.label.strip().strip("()").strip() == "i"
             and n.depth == 1),
            None,
        )
        assert node_i is not None
        assert node_i.level_type == "alpha"

    def test_i_as_alpha_via_lookahead_j(self) -> None:
        """When backward context is weak, (j) lookahead should force alpha (i)."""
        text = (
            "(a) First.\n"
            "(b) Second.\n"
            "(i) Ninth as alpha.\n"
            "(j) Tenth as alpha.\n"
        )
        nodes = parse_clauses(text)
        node_i = next((n for n in nodes if n.label.strip().strip("()").strip() == "i"), None)
        assert node_i is not None
        assert node_i.level_type == "alpha"
        assert node_i.depth == 1

    def test_i_as_roman_via_lookahead_ii(self) -> None:
        """(ii) lookahead should keep (i) as roman under a parent."""
        text = (
            "(a) Parent:\n"
            "(i) first roman child;\n"
            "(ii) second roman child;\n"
        )
        nodes = parse_clauses(text)
        node_i = next((n for n in nodes if n.label.strip().strip("()").strip() == "i"), None)
        assert node_i is not None
        assert node_i.level_type == "roman"
        assert node_i.depth == 2

    def test_x_as_alpha_via_lookahead_y(self) -> None:
        """(y) lookahead should keep ambiguous (x) in alpha run."""
        text = (
            "(u) item u.\n"
            "(x) item x.\n"
            "(y) item y.\n"
        )
        nodes = parse_clauses(text)
        node_x = next((n for n in nodes if n.label.strip().strip("()").strip() == "x"), None)
        assert node_x is not None
        assert node_x.level_type == "alpha"
        assert node_x.depth == 1

    def test_v_as_roman_via_lookahead_vi(self) -> None:
        """(vi) lookahead should keep ambiguous (v) in roman run."""
        text = (
            "(a) Parent:\n"
            "(v) fifth roman child;\n"
            "(vi) sixth roman child;\n"
        )
        nodes = parse_clauses(text)
        node_v = next((n for n in nodes if n.label.strip().strip("()").strip() == "v"), None)
        assert node_v is not None
        assert node_v.level_type == "roman"
        assert node_v.depth == 2


# ===========================================================================
# High-letter continuation handling
# ===========================================================================


class TestHighLetterContinuationRepair:
    def test_x_midline_after_and_gets_nested(self) -> None:
        """Inline high-letter continuation should nest under root alpha."""
        text = (
            "(a) Parent clause with continuing conditions and (x) no default exists;\n"
            "(b) Next clause.\n"
        )
        nodes = parse_clauses(text)
        node_x = next((n for n in nodes if n.label.strip().strip("()").strip() == "x"), None)
        assert node_x is not None
        assert node_x.parent_id == "a"

    def test_x_at_line_start_with_long_body_stays_root(self) -> None:
        """Anchored high-letter with substantive body should remain root-level."""
        long_body = " ".join(["substantive"] * 80)
        text = (
            "(a) Opening clause.\n"
            "(x) " + long_body + "\n"
            "(y) next root clause with text.\n"
        )
        nodes = parse_clauses(text)
        node_x = next((n for n in nodes if n.label.strip().strip("()").strip() == "x"), None)
        assert node_x is not None
        assert node_x.parent_id == ""

    def test_semicolon_only_boundary_does_not_force_nesting(self) -> None:
        """Semicolons alone should not force high-letter continuation nesting."""
        text = (
            "(a) alpha;\n"
            "(b) beta;\n"
            "(c) gamma;\n"
            "(x) root high-letter clause.\n"
            "(y) root high-letter sibling.\n"
        )
        nodes = parse_clauses(text)
        node_x = next((n for n in nodes if n.label.strip().strip("()").strip() == "x"), None)
        node_y = next((n for n in nodes if n.label.strip().strip("()").strip() == "y"), None)
        assert node_x is not None and node_y is not None
        assert node_x.parent_id == ""
        assert node_y.parent_id == ""


# ===========================================================================
# Phase 2: Enhanced xref detection
# ===========================================================================


class TestXrefDetection:
    def test_section_xref_lookback(self) -> None:
        """'pursuant to Section 4.01(a)' — (a) should be xref."""
        text = "The obligations set forth pursuant to Section 4.01(a) shall apply to all parties."
        nodes = parse_clauses(text)
        if nodes:
            node_a = nodes[0]
            assert node_a.xref_suspected

    def test_clause_xref_above(self) -> None:
        """'as described in clause (iii) above' — (iii) should be xref."""
        text = "as described in clause (iii) above and herein incorporated."
        nodes = parse_clauses(text)
        if nodes:
            assert nodes[0].xref_suspected

    def test_structural_not_xref(self) -> None:
        """'(a) The Borrower shall...' at line start — NOT xref."""
        text = "(a) The Borrower shall comply.\n(b) The Agent shall notify.\n"
        nodes = parse_clauses(text)
        assert nodes
        assert not nodes[0].xref_suspected

    def test_xref_lookahead_hereof(self) -> None:
        """'clause (b) hereof' — (b) should be xref."""
        text = "subject to the provisions of clause (b) hereof, the Borrower shall comply."
        nodes = parse_clauses(text)
        if nodes:
            node_b = next(
                (n for n in nodes if n.label.strip().strip("()").strip() == "b"),
                None,
            )
            if node_b:
                assert node_b.xref_suspected

    def test_xref_lookahead_hereunder(self) -> None:
        """'clause (c) hereunder' — (c) should be xref."""
        text = "as required by clause (c) hereunder, the Agent shall comply."
        nodes = parse_clauses(text)
        if nodes:
            node_c = next(
                (n for n in nodes if n.label.strip().strip("()").strip() == "c"),
                None,
            )
            if node_c:
                assert node_c.xref_suspected

    def test_section_xref_and_b(self) -> None:
        """'Section 2.14(a) and (b)' — both (a) and (b) should be xref."""
        text = "pursuant to Section 2.14(a) and (b) of this Agreement, the Borrower shall comply."
        nodes = parse_clauses(text)
        assert len(nodes) >= 2
        for n in nodes:
            assert n.xref_suspected, f"Node {n.id} should be xref_suspected"

    def test_pursuant_to_clause_xref(self) -> None:
        """'pursuant to clause (i)' should be xref."""
        text = "the Borrower may incur debt pursuant to clause (i) of this Section."
        nodes = parse_clauses(text)
        assert nodes
        assert nodes[0].xref_suspected

    def test_subject_to_paragraph_xref(self) -> None:
        """'subject to paragraph (ii) above' should be xref."""
        text = "subject to paragraph (ii) above, the Borrower may proceed."
        nodes = parse_clauses(text)
        assert nodes
        assert nodes[0].xref_suspected

    def test_subject_to_bare_not_xref(self) -> None:
        """Bare 'subject to (a)' should not be treated as xref by context regex."""
        text = "subject to (a) the following conditions shall apply."
        nodes = parse_clauses(text)
        assert nodes
        assert not nodes[0].xref_suspected

    def test_defined_in_clause_xref(self) -> None:
        """'defined in clause (iii)' should be xref."""
        text = "as defined in clause (iii) of this Agreement."
        nodes = parse_clauses(text)
        assert nodes
        assert nodes[0].xref_suspected


# ===========================================================================
# Phase 3: 5-signal confidence scoring
# ===========================================================================


class TestConfidenceScoring:
    def test_singleton_demoted(self) -> None:
        """Weak singleton (xref) should remain demoted after penalty."""
        text = "pursuant to clause (i) of this Section."
        nodes = parse_clauses(text)
        singleton_nodes = [n for n in nodes if n.demotion_reason == "singleton"]
        assert len(singleton_nodes) >= 1

    def test_anchored_singleton_promoted(self) -> None:
        """Anchored, non-xref singleton should survive penalty and remain structural."""
        text = (
            "(a) Parent section:\n"
            "(i) sole operative child clause with substantive body text.\n"
            "(b) Next parent section.\n"
        )
        nodes = parse_clauses(text)
        node_i = next((n for n in nodes if n.label.strip().strip("()").strip() == "i"), None)
        assert node_i is not None
        assert node_i.is_structural_candidate
        assert node_i.parse_confidence >= 0.5

    def test_reserved_singleton_structural(self) -> None:
        """Reserved/omitted singleton should bypass penalty and remain structural."""
        text = "(a) Reserved.\n(b) Active clause text.\n"
        nodes = parse_clauses(text)
        node_a = next((n for n in nodes if n.id == "a"), None)
        assert node_a is not None
        assert node_a.is_structural_candidate
        assert node_a.demotion_reason == ""

    def test_unanchored_singleton_still_demoted(self) -> None:
        """Inline singleton should remain demoted due weak confidence."""
        text = "The parties agree that (i) this inline singleton is not structural."
        nodes = parse_clauses(text)
        assert nodes
        node_i = nodes[0]
        assert not node_i.is_structural_candidate
        assert node_i.demotion_reason == "singleton"

    def test_run_of_three_high_confidence(self) -> None:
        """Run of (a), (b), (c) at line start should have high confidence."""
        text = (
            "(a) The Borrower shall comply.\n"
            "(b) The Agent shall notify.\n"
            "(c) The Lender shall provide.\n"
        )
        nodes = parse_clauses(text)
        for n in nodes:
            if n.level_type == "alpha":
                assert n.parse_confidence >= 0.6

    def test_confidence_always_bounded(self) -> None:
        """Confidence always in [0.0, 1.0]."""
        text = NESTED_CLAUSE_TEXT
        nodes = parse_clauses(text)
        for n in nodes:
            assert 0.0 <= n.parse_confidence <= 1.0

    def test_structural_candidate_threshold(self) -> None:
        """is_structural_candidate = True only when confidence >= 0.5."""
        text = NESTED_CLAUSE_TEXT
        nodes = parse_clauses(text)
        for n in nodes:
            if n.is_structural_candidate:
                assert n.parse_confidence >= 0.5

    def test_indentation_score_present(self) -> None:
        """All nodes should have indentation_score in [0.0, 1.0]."""
        text = NESTED_CLAUSE_TEXT
        nodes = parse_clauses(text)
        for n in nodes:
            assert 0.0 <= n.indentation_score <= 1.0


# ===========================================================================
# Phase 4: Ghost clause filtering
# ===========================================================================


class TestGhostClauseFiltering:
    def test_ghost_period_only(self) -> None:
        """'(b) .' should be a ghost clause."""
        text = "(a) The Borrower shall comply.\n(b) .\n(c) The Lender shall provide.\n"
        nodes = parse_clauses(text)
        node_b = next((n for n in nodes if n.id == "b"), None)
        assert node_b is not None
        assert not node_b.is_structural_candidate
        assert node_b.demotion_reason == "ghost_body"

    def test_ghost_whitespace_only(self) -> None:
        """'(c)  ' with only whitespace body should be ghost."""
        text = "(a) The Borrower shall comply.\n(b) The Lender agrees.\n(c)  \n"
        nodes = parse_clauses(text)
        node_c = next((n for n in nodes if n.id == "c"), None)
        assert node_c is not None
        assert not node_c.is_structural_candidate
        assert node_c.demotion_reason == "ghost_body"

    def test_not_ghost_legal_content(self) -> None:
        """'(a) The Borrower shall' is NOT a ghost."""
        text = (
            "(a) The Borrower shall comply with all provisions.\n"
            "(b) The Agent shall notify the parties.\n"
        )
        nodes = parse_clauses(text)
        node_a = next((n for n in nodes if n.id == "a"), None)
        assert node_a is not None
        assert node_a.is_structural_candidate

    def test_short_list_clause_not_ghost(self) -> None:
        """Short list-style clauses like '(b) Capital Expenditures;' are NOT ghost."""
        text = (
            "(a) Permitted Investments;\n"
            "(b) Capital Expenditures;\n"
            "(c) Restricted Payments;\n"
        )
        nodes = parse_clauses(text)
        for n in nodes:
            assert n.demotion_reason != "ghost_body", (
                f"Node {n.id} with body should not be ghost-demoted"
            )


# ===========================================================================
# Phase 5: Schema alignment
# ===========================================================================


class TestSchemaAlignment:
    def test_clause_node_has_indentation_score(self) -> None:
        nodes = parse_clauses(NESTED_CLAUSE_TEXT)
        assert nodes
        assert hasattr(nodes[0], "indentation_score")
        assert isinstance(nodes[0].indentation_score, float)

    def test_clause_node_has_xref_suspected(self) -> None:
        nodes = parse_clauses(NESTED_CLAUSE_TEXT)
        assert nodes
        assert hasattr(nodes[0], "xref_suspected")
        assert isinstance(nodes[0].xref_suspected, bool)

    def test_as_records_includes_new_fields(self) -> None:
        tree = ClauseTree.from_text(NESTED_CLAUSE_TEXT)
        records = tree.as_records()
        assert records
        assert "indentation_score" in records[0]
        assert "xref_suspected" in records[0]

    def test_clause_node_frozen(self) -> None:
        """ClauseNode should be frozen (immutable)."""
        nodes = parse_clauses(NESTED_CLAUSE_TEXT)
        assert nodes
        try:
            nodes[0].depth = 99  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass  # Expected


# ===========================================================================
# Phase 6: Inline enumeration detection
# ===========================================================================


class TestInlineEnumDetection:
    def test_inline_comma_and_pattern(self) -> None:
        """'items (x), (y) and (z)' on one line — all should be xref."""
        text = "items (x), (y) and (z) in the agreement shall apply.\n"
        nodes = parse_clauses(text)
        for n in nodes:
            assert n.xref_suspected, f"Node {n.id} should be xref_suspected"

    def test_one_per_line_not_inline(self) -> None:
        """'(a)\\n(b)\\n(c)' on separate lines — NOT inline."""
        text = (
            "(a) The Borrower shall comply.\n"
            "(b) The Lender agrees.\n"
            "(c) The Agent shall notify.\n"
        )
        nodes = parse_clauses(text)
        # These are structural, not inline references
        for n in nodes:
            assert not n.xref_suspected

    def test_inline_or_pattern(self) -> None:
        """'clauses (a), (b) or (c)' — all should be inline xref."""
        text = "pursuant to clauses (a), (b) or (c) of this Section, the Borrower shall comply.\n"
        nodes = parse_clauses(text)
        for n in nodes:
            assert n.xref_suspected, f"Node {n.id} should be xref_suspected"

    def test_inline_and_or_pattern(self) -> None:
        """'clauses (a) and/or (b)' — both should be inline xref."""
        text = "pursuant to clauses (a) and/or (b) of this Section, the Borrower shall comply.\n"
        nodes = parse_clauses(text)
        for n in nodes:
            assert n.xref_suspected, f"Node {n.id} should be xref_suspected"

    def test_inline_two_element(self) -> None:
        """'clauses (a) and (b)' — 2-element inline should be detected."""
        text = "clauses (a) and (b) hereof shall apply to all parties.\n"
        nodes = parse_clauses(text)
        assert len(nodes) >= 2
        for n in nodes:
            assert n.xref_suspected, f"Node {n.id} should be xref_suspected"


# ===========================================================================
# ClauseTree wrapper tests
# ===========================================================================


WRAPPER_SAMPLE = """
(a) The Borrower shall not incur debt.
(b) The Borrower may incur Permitted Debt.
    (i) ratio debt.
    (ii) acquisition debt.
"""


class TestClauseTreeWrapper:
    def test_clause_tree_from_text(self) -> None:
        tree = ClauseTree.from_text(WRAPPER_SAMPLE)
        assert tree.nodes
        assert tree.roots

    def test_clause_tree_resolve_path(self) -> None:
        from agent.clause_parser import parse_clause_tree
        tree = parse_clause_tree(WRAPPER_SAMPLE)
        node = tree.resolve(["(b)", "(i)"])
        assert node is not None
        assert node.label.lower().startswith("(i")

    def test_clause_tree_children_of(self) -> None:
        tree = ClauseTree.from_text(WRAPPER_SAMPLE)
        node_b = next((n for n in tree.nodes if n.id == "b"), None)
        if node_b:
            children = tree.children_of("b")
            assert len(children) >= 2

    def test_clause_tree_node_by_id(self) -> None:
        tree = ClauseTree.from_text(WRAPPER_SAMPLE)
        node = tree.node_by_id("a")
        assert node is not None
        assert node.label.strip() == "(a)"


# ===========================================================================
# Phase 7: Parser artifact prevention
# ===========================================================================


class TestPeriodDelimitedEnumerators:
    """Verify period-delimited enumerators produce clean clause IDs."""

    def test_period_labels_strip_trailing_dot(self) -> None:
        """Period-delimited enumerators (a. b. c.) should NOT have trailing dots in IDs."""
        text = (
            "a. The Borrower shall comply with all terms and conditions.\n"
            "b. Any Subsidiary may request extensions to the facility.\n"
            "c. Total amounts shall not exceed the permitted limits.\n"
        )
        nodes = parse_clauses(text)
        assert len(nodes) >= 3
        for node in nodes:
            assert not node.id.endswith("."), f"Clause ID '{node.id}' has trailing dot"
            assert "._" not in node.id, f"Clause ID '{node.id}' has dot-underscore segment"
        # Verify the IDs are clean single-char labels
        ids = [n.id for n in nodes if not n.xref_suspected]
        assert "a" in ids
        assert "b" in ids
        assert "c" in ids

    def test_nested_period_labels_clean(self) -> None:
        """Nested period-delimited enumerators should produce clean dot-path IDs."""
        text = (
            "(a) The Borrower shall comply with all terms:\n"
            "1. first sub-provision of clause a;\n"
            "2. second sub-provision of clause a;\n"
            "(b) Any Subsidiary may request extensions.\n"
        )
        nodes = parse_clauses(text)
        structural = [n for n in nodes if not n.xref_suspected]
        for node in structural:
            assert not node.id.endswith("."), f"Clause ID '{node.id}' has trailing dot"


class TestDuplicateIdFormat:
    """Verify duplicate clause IDs use _dup suffix format."""

    def test_duplicate_id_uses_dup_suffix(self) -> None:
        """Duplicate clause IDs should use _dup prefix, not bare underscore counter."""
        # Two identical (a) enumerators at root level forces a dup
        text = (
            "(a) First provision with enough text to be structural.\n"
            "(a) Second provision with enough text to be structural.\n"
        )
        nodes = parse_clauses(text)
        structural = [n for n in nodes if not n.xref_suspected]
        if len(structural) > 1:
            ids = [n.id for n in structural]
            dup_ids = [i for i in ids if "_dup" in i]
            assert len(dup_ids) >= 1, f"Expected _dup suffix in IDs: {ids}"
            for did in dup_ids:
                assert "._" not in did, f"Dup ID '{did}' has dot-underscore segment"
