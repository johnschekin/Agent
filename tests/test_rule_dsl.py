"""Tests for agent.rule_dsl — Text DSL parser for family link rules."""
from __future__ import annotations

import pytest

from agent.query_filters import (
    FilterGroup,
    FilterMatch,
    MetaFilterNumeric,
    MetaFilterString,
)
from agent.rule_dsl import (
    DslParseResult,
    MacroRef,
    ProximityOp,
    _tokenize,
    dsl_from_heading_ast,
    expand_term_suggestions,
    heading_ast_from_dsl,
    parse_dsl,
    serialize_dsl,
    validate_dsl,
)


# ───────────────────────────── Tokenizer ─────────────────────────────


class TestTokenizer:
    def test_simple_tokens(self) -> None:
        tokens = _tokenize('heading: Indebtedness & !Lien')
        kinds = [t.kind for t in tokens if t.kind != "EOF"]
        assert kinds == ["BARE_WORD", "FIELD_SEP", "BARE_WORD", "AMP", "BANG", "BARE_WORD"]

    def test_quoted_string(self) -> None:
        tokens = _tokenize('"Limitation on Indebtedness"')
        assert tokens[0].kind == "QUOTED_STRING"
        assert tokens[0].value == '"Limitation on Indebtedness"'

    def test_regex(self) -> None:
        tokens = _tokenize('/indebt.*/')
        assert tokens[0].kind == "REGEX"
        assert tokens[0].value == "/indebt.*/"

    def test_macro_ref(self) -> None:
        tokens = _tokenize('@debt_synonyms')
        assert tokens[0].kind == "MACRO_REF"
        assert tokens[0].value == "@debt_synonyms"

    def test_proximity_ops(self) -> None:
        tokens = _tokenize('/s /p /5')
        kinds = [t.kind for t in tokens if t.kind != "EOF"]
        assert kinds == ["PROX_OP", "PROX_OP", "PROX_N"]

    def test_numeric_op(self) -> None:
        tokens = _tokenize('facility_size_mm > 500')
        kinds = [t.kind for t in tokens if t.kind != "EOF"]
        assert "NUMERIC_OP" in kinds

    def test_pipe_and_parens(self) -> None:
        tokens = _tokenize('(A | B)')
        kinds = [t.kind for t in tokens if t.kind != "EOF"]
        assert kinds == ["LPAREN", "BARE_WORD", "PIPE", "BARE_WORD", "RPAREN"]


# ───────────────────────────── Basic parsing ─────────────────────────


class TestBasicParsing:
    def test_single_heading_term(self) -> None:
        result = parse_dsl("heading: Indebtedness")
        assert result.ok
        assert "heading" in result.text_fields
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterMatch)
        assert expr.value == "Indebtedness"

    def test_heading_or(self) -> None:
        result = parse_dsl("heading: Indebtedness | Debt")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "or"
        assert len(expr.children) == 2

    def test_heading_and(self) -> None:
        result = parse_dsl("heading: Indebtedness & !Lien")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"

    def test_heading_and_not(self) -> None:
        result = parse_dsl("heading: Indebtedness & !Lien & !Pledge")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"
        assert len(expr.children) == 3
        # Second and third children should be negated
        c1 = expr.children[1]
        c2 = expr.children[2]
        assert isinstance(c1, FilterMatch) and c1.negate
        assert isinstance(c2, FilterMatch) and c2.negate

    def test_heading_grouped_or_and_not(self) -> None:
        """heading: (Indebtedness | "Limitation on Indebtedness") & !Lien"""
        result = parse_dsl('heading: (Indebtedness | "Limitation on Indebtedness") & !Lien')
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"

    def test_article_field(self) -> None:
        result = parse_dsl("article: negative_covenants")
        assert result.ok
        assert "article" in result.text_fields

    def test_section_field(self) -> None:
        result = parse_dsl("section: definitions")
        assert result.ok
        assert "section" in result.text_fields

    def test_defined_term_field(self) -> None:
        result = parse_dsl('defined_term: "Permitted Liens"')
        assert result.ok
        assert "defined_term" in result.text_fields
        expr = result.text_fields["defined_term"]
        assert isinstance(expr, FilterMatch)
        assert expr.value == "Permitted Liens"

    def test_quoted_string_value(self) -> None:
        result = parse_dsl('heading: "Limitation on Indebtedness"')
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterMatch)
        assert expr.value == "Limitation on Indebtedness"


# ───────────────────── Multiple field clauses ─────────────────────────


class TestMultipleFieldClauses:
    def test_heading_and_article(self) -> None:
        result = parse_dsl("heading: Indebtedness\narticle: negative_covenants")
        assert result.ok
        assert "heading" in result.text_fields
        assert "article" in result.text_fields

    def test_heading_and_defined_term(self) -> None:
        result = parse_dsl('heading: Liens\ndefined_term: "Permitted Liens"')
        assert result.ok
        assert "heading" in result.text_fields
        assert "defined_term" in result.text_fields


# ───────────────────── Proximity operators ────────────────────────────


class TestProximity:
    def test_same_sentence(self) -> None:
        result = parse_dsl('clause: "incur" /s "Debt"')
        assert result.ok
        expr = result.text_fields["clause"]
        assert isinstance(expr, ProximityOp)
        assert expr.kind == "sentence"

    def test_same_paragraph(self) -> None:
        result = parse_dsl('clause: "incur" /p "Debt"')
        assert result.ok
        expr = result.text_fields["clause"]
        assert isinstance(expr, ProximityOp)
        assert expr.kind == "paragraph"

    def test_within_n_words(self) -> None:
        result = parse_dsl('clause: "Limitation" /5 "Lien"')
        assert result.ok
        expr = result.text_fields["clause"]
        assert isinstance(expr, ProximityOp)
        assert expr.kind == "words"
        assert expr.distance == 5

    def test_proximity_rejected_on_heading(self) -> None:
        """Proximity operators only valid on clause field."""
        result = parse_dsl('heading: Indebtedness /s Debt')
        assert not result.ok
        assert any("clause" in e.message.lower() or "proximity" in e.message.lower()
                    for e in result.errors)

    def test_proximity_with_macro(self) -> None:
        macros = {
            "lien_phrases": FilterGroup(
                operator="or",
                children=(FilterMatch(value="Lien"), FilterMatch(value="Pledge")),
            ),
        }
        result = parse_dsl('clause: @lien_phrases /s "incur"', macros)
        assert result.ok
        expr = result.text_fields["clause"]
        assert isinstance(expr, ProximityOp)


# ───────────────────── Regex ──────────────────────────────────────────


class TestRegex:
    def test_regex_match(self) -> None:
        result = parse_dsl("heading: /indebt.*/")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterMatch)
        assert expr.value == "/indebt.*/"

    def test_regex_invalid_syntax(self) -> None:
        result = parse_dsl("heading: /[invalid/")
        assert not result.ok
        assert any("regex" in e.message.lower() for e in result.errors)

    def test_regex_combined_with_and(self) -> None:
        result = parse_dsl("heading: /indebt.*/ & !Lien")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)


# ───────────────────── Macros ─────────────────────────────────────────


class TestMacros:
    def test_macro_expansion(self) -> None:
        macros = {
            "debt_synonyms": FilterGroup(
                operator="or",
                children=(
                    FilterMatch(value="Indebtedness"),
                    FilterMatch(value="Debt"),
                    FilterMatch(value="Borrowed Money"),
                ),
            ),
        }
        result = parse_dsl("heading: @debt_synonyms", macros)
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "or"
        assert len(expr.children) == 3

    def test_macro_combined_with_not(self) -> None:
        macros = {
            "debt_synonyms": FilterGroup(
                operator="or",
                children=(FilterMatch(value="Indebtedness"), FilterMatch(value="Debt")),
            ),
        }
        result = parse_dsl("heading: @debt_synonyms & !Lien", macros)
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"

    def test_undefined_macro_error(self) -> None:
        result = parse_dsl("heading: @nonexistent")
        assert not result.ok
        assert any("Undefined macro" in e.message for e in result.errors)

    def test_circular_macro_error(self) -> None:
        """Circular references: A → B → A should be detected."""
        macros = {
            "a": MacroRef(name="b"),
            "b": MacroRef(name="a"),
        }
        result = parse_dsl("heading: @a", macros)
        assert not result.ok
        assert any("Circular macro reference" in e.message for e in result.errors)

    def test_macro_with_proximity(self) -> None:
        macros = {
            "debt_synonyms": FilterGroup(
                operator="or",
                children=(FilterMatch(value="Debt"), FilterMatch(value="Indebtedness")),
            ),
        }
        result = parse_dsl('clause: @debt_synonyms /s "incur"', macros)
        assert result.ok
        expr = result.text_fields["clause"]
        assert isinstance(expr, ProximityOp)


# ───────────────────── Metadata fields ────────────────────────────────


class TestMetaFields:
    def test_template_string(self) -> None:
        result = parse_dsl("template: kirkland")
        assert result.ok
        assert "template" in result.meta_fields
        meta = result.meta_fields["template"]
        assert isinstance(meta, MetaFilterString)

    def test_vintage_string(self) -> None:
        result = parse_dsl("vintage: 2024")
        assert result.ok
        assert "vintage" in result.meta_fields

    def test_market_string(self) -> None:
        result = parse_dsl("market: bsl")
        assert result.ok
        assert "market" in result.meta_fields

    def test_doc_type(self) -> None:
        result = parse_dsl("doc_type: credit_agreement")
        assert result.ok
        assert "doc_type" in result.meta_fields

    def test_admin_agent(self) -> None:
        result = parse_dsl('admin_agent: "JPMorgan"')
        assert result.ok
        assert "admin_agent" in result.meta_fields

    def test_facility_size_numeric(self) -> None:
        result = parse_dsl("facility_size_mm > 500")
        assert result.ok
        assert "facility_size_mm" in result.meta_fields
        meta = result.meta_fields["facility_size_mm"]
        assert isinstance(meta, MetaFilterNumeric)
        assert meta.operator == ">"
        assert meta.value == 500.0

    def test_facility_size_less_equal(self) -> None:
        result = parse_dsl("facility_size_mm <= 1000")
        assert result.ok
        meta = result.meta_fields["facility_size_mm"]
        assert isinstance(meta, MetaFilterNumeric)
        assert meta.operator == "<="

    def test_mixed_text_and_meta(self) -> None:
        result = parse_dsl("heading: Indebtedness\ntemplate: kirkland\nvintage: 2024")
        assert result.ok
        assert "heading" in result.text_fields
        assert "template" in result.meta_fields
        assert "vintage" in result.meta_fields

    def test_meta_or_group(self) -> None:
        result = parse_dsl("market: (bsl | ig)")
        assert result.ok
        meta = result.meta_fields["market"]
        assert isinstance(meta, MetaFilterString)
        assert isinstance(meta.expr, FilterGroup)
        assert meta.expr.operator == "or"


# ───────────────────── Serialization round-trip ───────────────────────


class TestSerialize:
    def test_simple_heading(self) -> None:
        result = parse_dsl("heading: Indebtedness")
        assert result.ok
        normalized = serialize_dsl(result.text_fields, result.meta_fields)
        assert "heading: Indebtedness" in normalized

    def test_or_group(self) -> None:
        result = parse_dsl("heading: Indebtedness | Debt")
        assert result.ok
        normalized = serialize_dsl(result.text_fields, result.meta_fields)
        assert "heading: (Indebtedness | Debt)" in normalized

    def test_and_not(self) -> None:
        result = parse_dsl("heading: Indebtedness & !Lien")
        assert result.ok
        normalized = serialize_dsl(result.text_fields, result.meta_fields)
        assert "heading:" in normalized
        assert "!Lien" in normalized

    def test_proximity(self) -> None:
        result = parse_dsl('clause: "incur" /s "Debt"')
        assert result.ok
        normalized = serialize_dsl(result.text_fields, result.meta_fields)
        assert '/s' in normalized

    def test_proximity_n(self) -> None:
        result = parse_dsl('clause: "Limitation" /5 "Lien"')
        assert result.ok
        normalized = serialize_dsl(result.text_fields, result.meta_fields)
        assert "/5" in normalized

    def test_round_trip_normalize(self) -> None:
        """serialize(parse(t)) normalizes t."""
        text = 'heading:  (  Indebtedness | Debt ) &  !Lien'
        result = parse_dsl(text)
        assert result.ok
        normalized = serialize_dsl(result.text_fields, result.meta_fields)
        # Re-parse the normalized version
        result2 = parse_dsl(normalized)
        assert result2.ok
        normalized2 = serialize_dsl(result2.text_fields, result2.meta_fields)
        # Normalized form should be stable
        assert normalized == normalized2

    def test_meta_serialize(self) -> None:
        result = parse_dsl("facility_size_mm > 500")
        assert result.ok
        normalized = serialize_dsl(result.text_fields, result.meta_fields)
        assert "facility_size_mm" in normalized
        assert "> 500" in normalized

    def test_quoted_string_round_trip(self) -> None:
        result = parse_dsl('heading: "Limitation on Indebtedness"')
        assert result.ok
        normalized = serialize_dsl(result.text_fields, result.meta_fields)
        assert '"Limitation on Indebtedness"' in normalized


# ───────────────────── Query cost ─────────────────────────────────────


class TestQueryCost:
    def test_simple_has_low_cost(self) -> None:
        result = parse_dsl("heading: Indebtedness")
        assert result.query_cost > 0
        assert result.query_cost < 10

    def test_proximity_increases_cost(self) -> None:
        simple = parse_dsl("clause: incur")
        prox = parse_dsl('clause: "incur" /s "Debt"')
        assert prox.query_cost > simple.query_cost

    def test_cost_scales_with_complexity(self) -> None:
        simple = parse_dsl("heading: A")
        complex_ = parse_dsl("heading: (A | B | C | D) & !E & !F")
        assert complex_.query_cost > simple.query_cost


# ───────────────────── Validation ─────────────────────────────────────


class TestValidation:
    def test_valid_dsl_passes(self) -> None:
        result = validate_dsl("heading: Indebtedness & !Lien")
        assert result.ok

    def test_unknown_field_error(self) -> None:
        result = parse_dsl("bogus: test")
        assert not result.ok
        assert any("field name" in e.message.lower() for e in result.errors)

    def test_empty_input_no_crash(self) -> None:
        result = parse_dsl("")
        assert result.ok  # Empty is valid (no field clauses)
        assert len(result.text_fields) == 0
        assert len(result.meta_fields) == 0


# ───────────────────── Term expansion ─────────────────────────────────


class TestExpandTerm:
    def test_no_sources(self) -> None:
        suggestions = expand_term_suggestions("Indebtedness")
        assert suggestions == []

    def test_ontology_synonyms(self) -> None:
        suggestions = expand_term_suggestions(
            "Indebtedness",
            ontology_synonyms=["Debt", "Borrowed Money", "Advances"],
        )
        assert "Debt" in suggestions
        assert "Borrowed Money" in suggestions
        assert "Advances" in suggestions

    def test_dedup_case_insensitive(self) -> None:
        suggestions = expand_term_suggestions(
            "Indebtedness",
            ontology_synonyms=["indebtedness", "Debt"],
        )
        assert "indebtedness" not in suggestions
        assert "Debt" in suggestions

    def test_heading_cooccurrence(self) -> None:
        suggestions = expand_term_suggestions(
            "Liens",
            heading_cooccurrence=["Pledges", "Security Interests"],
        )
        assert "Pledges" in suggestions
        assert "Security Interests" in suggestions

    def test_both_sources_deduped(self) -> None:
        suggestions = expand_term_suggestions(
            "Liens",
            ontology_synonyms=["Pledges", "Encumbrances"],
            heading_cooccurrence=["Pledges", "Security Interests"],
        )
        # "Pledges" appears in both but should only appear once
        assert suggestions.count("Pledges") == 1
        assert "Encumbrances" in suggestions
        assert "Security Interests" in suggestions

    def test_excludes_original(self) -> None:
        suggestions = expand_term_suggestions(
            "Liens",
            ontology_synonyms=["Liens", "Pledges"],
        )
        assert "Liens" not in suggestions


# ───────────────────── AND / OR / NOT aliases ─────────────────────────


class TestAliases:
    def test_and_alias(self) -> None:
        result = parse_dsl("heading: Indebtedness AND Debt")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"
        assert len(expr.children) == 2

    def test_or_alias(self) -> None:
        result = parse_dsl("heading: Indebtedness OR Debt")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "or"
        assert len(expr.children) == 2

    def test_not_alias(self) -> None:
        result = parse_dsl("heading: Indebtedness AND NOT Lien")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"
        assert len(expr.children) == 2
        c1 = expr.children[1]
        assert isinstance(c1, FilterMatch) and c1.negate

    def test_case_insensitive_aliases(self) -> None:
        """and, Or, NOT all work regardless of case."""
        for op_text, expected_op in [("and", "and"), ("Or", "or")]:
            result = parse_dsl(f"heading: A {op_text} B")
            assert result.ok, f"Failed for: {op_text}"
            expr = result.text_fields["heading"]
            assert isinstance(expr, FilterGroup)
            assert expr.operator == expected_op

        result = parse_dsl("heading: A & not B")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        c1 = expr.children[1]
        assert isinstance(c1, FilterMatch) and c1.negate

    def test_mixed_aliases_and_symbols(self) -> None:
        """heading: A & B OR C should parse as (A & B) | C"""
        result = parse_dsl("heading: A & B OR C")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "or"

    def test_normalized_output_uses_symbols(self) -> None:
        """Serialized output always uses & | ! — never AND OR NOT."""
        result = parse_dsl("heading: A AND B OR C")
        assert result.ok
        normalized = result.normalized_text
        assert "AND" not in normalized
        assert "OR" not in normalized
        assert "&" in normalized or "|" in normalized

    def test_alias_as_bare_value_errors(self) -> None:
        """heading: AND should error — alias can't be a value."""
        result = parse_dsl("heading: AND")
        assert not result.ok
        assert any("operator" in e.message.lower() or "forget" in e.message.lower()
                    for e in result.errors)

    def test_alias_not_without_operand(self) -> None:
        """heading: NOT — NOT consumed as operator, no operand → empty result."""
        # NOT is a prefix operator; without an operand after it,
        # the parse produces no field entry (NOT eats the token, but
        # the inner atom returns None which propagates up).
        result = parse_dsl("heading: NOT")
        # Key assertion: NOT should NOT appear as a literal value
        assert "heading" not in result.text_fields


# ───────────────────── Smarter error messages ─────────────────────────


class TestSmarterErrors:
    def test_close_field_suggestion(self) -> None:
        """Typo like 'headng' should suggest 'heading'."""
        result = parse_dsl("headng: test")
        assert not result.ok
        assert any("heading" in e.message for e in result.errors)

    def test_unexpected_alias_operator(self) -> None:
        """heading: AND should mention 'operator' in the error."""
        result = parse_dsl("heading: AND")
        assert not result.ok
        assert any("operator" in e.message.lower() for e in result.errors)


# ───────────────────── Edge cases ─────────────────────────────────────


class TestEdgeCases:
    def test_negation_of_bare_word(self) -> None:
        result = parse_dsl("heading: !Lien")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterMatch)
        assert expr.negate is True
        assert expr.value == "Lien"

    def test_double_negation(self) -> None:
        result = parse_dsl("heading: !!Lien")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterMatch)
        assert expr.negate is False  # double negation cancels out

    def test_nested_parens(self) -> None:
        result = parse_dsl("heading: ((A | B) & C)")
        assert result.ok
        expr = result.text_fields["heading"]
        assert isinstance(expr, FilterGroup)

    def test_all_five_text_fields(self) -> None:
        """All 5 text field types parse correctly."""
        for field in ["heading", "article", "clause", "section", "defined_term"]:
            result = parse_dsl(f"{field}: test_value")
            assert result.ok, f"Failed for field: {field}"
            assert field in result.text_fields

    def test_all_six_meta_fields(self) -> None:
        """All 6 meta field types parse correctly."""
        cases = [
            "template: kirkland",
            "vintage: 2024",
            "market: bsl",
            "doc_type: credit_agreement",
            'admin_agent: "JPMorgan"',
            "facility_size_mm > 500",
        ]
        for case in cases:
            result = parse_dsl(case)
            assert result.ok, f"Failed for: {case}"
            assert len(result.meta_fields) == 1


# ──────────── Bidirectional conversion: heading AST ↔ DSL ────────────


class TestDslFromHeadingAst:
    def test_single_match(self) -> None:
        ast = {"value": "Indebtedness"}
        dsl = dsl_from_heading_ast(ast)
        assert dsl == "heading: Indebtedness"

    def test_or_group(self) -> None:
        ast = {
            "op": "or",
            "children": [
                {"value": "Indebtedness"},
                {"value": "Limitation on Indebtedness"},
            ],
        }
        dsl = dsl_from_heading_ast(ast)
        assert "Indebtedness" in dsl
        assert '"Limitation on Indebtedness"' in dsl
        assert "|" in dsl
        assert dsl.startswith("heading: ")

    def test_empty_ast(self) -> None:
        assert dsl_from_heading_ast({}) == ""

    def test_invalid_ast(self) -> None:
        assert dsl_from_heading_ast({"bad": "data"}) == ""

    def test_negated_match(self) -> None:
        ast = {"value": "Liens", "negate": True}
        dsl = dsl_from_heading_ast(ast)
        assert "!Liens" in dsl

    def test_legacy_type_group(self) -> None:
        """Legacy format with 'type':'group' and 'operator':'or'."""
        ast = {
            "type": "group",
            "operator": "or",
            "children": [
                {"type": "match", "value": "Liens"},
                {"type": "match", "value": "Negative Pledge"},
            ],
        }
        dsl = dsl_from_heading_ast(ast)
        assert dsl.startswith("heading: ")
        assert "Liens" in dsl
        assert '"Negative Pledge"' in dsl


class TestHeadingAstFromDsl:
    def test_simple_heading(self) -> None:
        ast = heading_ast_from_dsl("heading: Indebtedness")
        assert ast is not None
        assert ast["value"] == "Indebtedness"

    def test_or_heading(self) -> None:
        ast = heading_ast_from_dsl('heading: Indebtedness | "Limitation on Indebtedness"')
        assert ast is not None
        assert ast.get("op") == "or"
        assert len(ast["children"]) == 2

    def test_no_heading_field(self) -> None:
        """DSL with only article field returns None."""
        ast = heading_ast_from_dsl('article: "negative covenants"')
        assert ast is None

    def test_multi_field_extracts_heading(self) -> None:
        """DSL with multiple fields still extracts heading."""
        ast = heading_ast_from_dsl('article: "negative covenants"\nheading: debt')
        assert ast is not None
        assert ast["value"] == "debt"

    def test_empty_input(self) -> None:
        assert heading_ast_from_dsl("") is None
        assert heading_ast_from_dsl("   ") is None

    def test_invalid_dsl(self) -> None:
        assert heading_ast_from_dsl("&&&invalid") is None

    def test_round_trip(self) -> None:
        """dsl_from_heading_ast → heading_ast_from_dsl round-trip."""
        original_ast = {
            "op": "or",
            "children": [
                {"value": "Liens"},
                {"value": "Limitation on Liens"},
            ],
        }
        dsl = dsl_from_heading_ast(original_ast)
        recovered = heading_ast_from_dsl(dsl)
        assert recovered is not None
        assert recovered.get("op") == "or"
        children = recovered["children"]
        values = {c["value"] for c in children}
        assert values == {"Liens", "Limitation on Liens"}
