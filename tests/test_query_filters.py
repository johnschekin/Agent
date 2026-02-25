"""Tests for agent.query_filters — AST filter expression system."""
from __future__ import annotations

import pytest

from agent.query_filters import (
    FilterGroup,
    FilterMatch,
    FilterValidationError,
    MetaFilterNumeric,
    MetaFilterString,
    build_filter_sql,
    build_legacy_terms_sql,
    build_meta_filter_sql,
    build_multi_field_sql,
    escape_like,
    estimate_query_cost,
    filter_expr_from_json,
    filter_expr_to_json,
    filter_terms_to_expr,
    meta_filter_from_json,
    meta_filter_to_json,
    validate_filter_expr,
)


# ───────────────────────────── escape_like ──────────────────────────────


class TestEscapeLike:
    def test_no_special(self) -> None:
        assert escape_like("hello") == "hello"

    def test_percent(self) -> None:
        assert escape_like("100%") == "100\\%"

    def test_underscore(self) -> None:
        assert escape_like("col_name") == "col\\_name"

    def test_both(self) -> None:
        assert escape_like("50%_off") == "50\\%\\_off"

    def test_backslash(self) -> None:
        assert escape_like("a\\b") == "a\\\\b"

    def test_empty(self) -> None:
        assert escape_like("") == ""


# ───────────────────────────── build_filter_sql ──────────────────────────


class TestBuildFilterSql:
    def test_single_match(self) -> None:
        expr = FilterMatch(value="Indebtedness")
        sql, params = build_filter_sql(expr, "s.heading")
        assert sql == "s.heading ILIKE ? ESCAPE '\\'"
        assert params == ["Indebtedness"]

    def test_single_negated(self) -> None:
        expr = FilterMatch(value="Lien", negate=True)
        sql, params = build_filter_sql(expr, "s.heading")
        assert sql == "s.heading NOT ILIKE ? ESCAPE '\\'"
        assert params == ["Lien"]

    def test_or_group(self) -> None:
        expr = FilterGroup(
            operator="or",
            children=(
                FilterMatch(value="Indebtedness"),
                FilterMatch(value="Limitation on Indebtedness"),
            ),
        )
        sql, params = build_filter_sql(expr, "s.heading")
        assert sql == (
            "(s.heading ILIKE ? ESCAPE '\\' OR s.heading ILIKE ? ESCAPE '\\')"
        )
        assert params == ["Indebtedness", "Limitation on Indebtedness"]

    def test_and_group(self) -> None:
        expr = FilterGroup(
            operator="and",
            children=(
                FilterMatch(value="Indebtedness"),
                FilterMatch(value="Lien", negate=True),
            ),
        )
        sql, params = build_filter_sql(expr, "s.heading")
        assert sql == (
            "(s.heading ILIKE ? ESCAPE '\\' AND "
            "s.heading NOT ILIKE ? ESCAPE '\\')"
        )
        assert params == ["Indebtedness", "Lien"]

    def test_nested_3_deep(self) -> None:
        """((A OR B) AND NOT C) — the spec example."""
        expr = FilterGroup(
            operator="and",
            children=(
                FilterGroup(
                    operator="or",
                    children=(
                        FilterMatch(value="Indebtedness"),
                        FilterMatch(value="Limitation on Indebtedness"),
                    ),
                ),
                FilterMatch(value="Lien", negate=True),
            ),
        )
        sql, params = build_filter_sql(expr, "s.heading")
        assert sql == (
            "((s.heading ILIKE ? ESCAPE '\\' OR s.heading ILIKE ? ESCAPE '\\') "
            "AND s.heading NOT ILIKE ? ESCAPE '\\')"
        )
        assert params == ["Indebtedness", "Limitation on Indebtedness", "Lien"]

    def test_deeply_nested(self) -> None:
        """4-level nesting."""
        inner: FilterMatch | FilterGroup = FilterMatch(value="deep")
        for _ in range(3):
            inner = FilterGroup(operator="and", children=(inner, FilterMatch(value="x")))
        sql, params = build_filter_sql(inner, "c")
        assert sql.count("(") == sql.count(")")
        assert len(params) == 4

    def test_wrap_wildcards(self) -> None:
        expr = FilterMatch(value="incur")
        sql, params = build_filter_sql(expr, "c.text", wrap_wildcards=True)
        assert sql == "c.text ILIKE ? ESCAPE '\\'"
        assert params == ["%incur%"]

    def test_wrap_wildcards_escapes(self) -> None:
        expr = FilterMatch(value="100%")
        sql, params = build_filter_sql(expr, "c.text", wrap_wildcards=True)
        assert params == ["%100\\%%"]

    def test_empty_group_produces_1eq1(self) -> None:
        expr = FilterGroup(operator="and", children=())
        sql, params = build_filter_sql(expr, "s.heading")
        assert sql == "(1=1)"
        assert params == []


# ───────────────────────── JSON round-trip ─────────────────────────────


class TestJsonRoundTrip:
    def test_leaf_simple(self) -> None:
        expr = FilterMatch(value="Liens")
        data = filter_expr_to_json(expr)
        assert data == {"value": "Liens"}
        restored = filter_expr_from_json(data)
        assert restored == expr

    def test_leaf_negated(self) -> None:
        expr = FilterMatch(value="Pledge", negate=True)
        data = filter_expr_to_json(expr)
        assert data == {"value": "Pledge", "negate": True}
        restored = filter_expr_from_json(data)
        assert restored == expr

    def test_group(self) -> None:
        expr = FilterGroup(
            operator="or",
            children=(
                FilterMatch(value="A"),
                FilterMatch(value="B"),
            ),
        )
        data = filter_expr_to_json(expr)
        assert data == {
            "op": "or",
            "children": [{"value": "A"}, {"value": "B"}],
        }
        restored = filter_expr_from_json(data)
        assert restored == expr

    def test_nested_round_trip(self) -> None:
        expr = FilterGroup(
            operator="and",
            children=(
                FilterGroup(
                    operator="or",
                    children=(
                        FilterMatch(value="Indebtedness"),
                        FilterMatch(value="Limitation on Indebtedness"),
                    ),
                ),
                FilterMatch(value="Lien", negate=True),
            ),
        )
        data = filter_expr_to_json(expr)
        restored = filter_expr_from_json(data)
        assert restored == expr

    def test_spec_json_example(self) -> None:
        """The exact JSON example from the plan spec."""
        data = {
            "op": "and",
            "children": [
                {
                    "op": "or",
                    "children": [
                        {"value": "Indebtedness"},
                        {"value": "Limitation on Indebtedness"},
                    ],
                },
                {"value": "Lien", "negate": True},
            ],
        }
        expr = filter_expr_from_json(data)
        sql, params = build_filter_sql(expr, "s.heading")
        assert sql == (
            "((s.heading ILIKE ? ESCAPE '\\' OR s.heading ILIKE ? ESCAPE '\\') "
            "AND s.heading NOT ILIKE ? ESCAPE '\\')"
        )
        assert params == ["Indebtedness", "Limitation on Indebtedness", "Lien"]

    def test_from_json_invalid_operator(self) -> None:
        with pytest.raises(ValueError, match="Invalid filter group operator"):
            filter_expr_from_json({"op": "xor", "children": []})

    def test_from_json_missing_children(self) -> None:
        with pytest.raises(ValueError, match="must be a list"):
            filter_expr_from_json({"op": "and", "children": "bad"})

    def test_from_json_unknown_shape(self) -> None:
        with pytest.raises(ValueError, match="Unrecognised"):
            filter_expr_from_json({"foo": "bar"})

    def test_from_json_legacy_shape_supported(self) -> None:
        data = {
            "type": "group",
            "operator": "or",
            "children": [
                {"type": "match", "value": "Indebtedness"},
                {"type": "match", "value": "Debt"},
            ],
        }
        expr = filter_expr_from_json(data)
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "or"
        assert len(expr.children) == 2

    def test_from_json_depth_limit_exceeded(self) -> None:
        data: dict[str, object] = {"value": "deep"}
        for _ in range(6):
            data = {"op": "and", "children": [data]}
        with pytest.raises(ValueError, match="depth"):
            filter_expr_from_json(data)

    def test_from_json_node_limit_exceeded(self) -> None:
        data = {"op": "or", "children": [{"value": f"v{i}"} for i in range(51)]}
        with pytest.raises(ValueError, match="nodes"):
            filter_expr_from_json(data)

    def test_from_json_wildcard_limit_exceeded(self) -> None:
        data = {"op": "or", "children": [{"value": f"%x{i}%"} for i in range(11)]}
        with pytest.raises(ValueError, match="wildcard"):
            filter_expr_from_json(data)


# ─────────────── Backward-compat (build_legacy_terms_sql) ─────────────


class TestBuildLegacyTermsSql:
    """Tests that build_legacy_terms_sql produces identical SQL to
    the old server.py _build_filter_group()."""

    def test_single_term(self) -> None:
        terms = [{"value": "Indebtedness", "op": "or"}]
        sql, params = build_legacy_terms_sql(terms, "s.heading")
        assert sql == "(s.heading ILIKE ? ESCAPE '\\')"
        assert params == ["Indebtedness"]

    def test_two_or_terms(self) -> None:
        terms = [
            {"value": "Indebtedness", "op": "or"},
            {"value": "Debt", "op": "or"},
        ]
        sql, params = build_legacy_terms_sql(terms, "s.heading")
        assert sql == "(s.heading ILIKE ? ESCAPE '\\' OR s.heading ILIKE ? ESCAPE '\\')"
        assert params == ["Indebtedness", "Debt"]

    def test_mixed_or_and_not(self) -> None:
        """Reproduces the exact output of _build_filter_group."""
        terms = [
            {"value": "Indebtedness", "op": "or"},
            {"value": "Debt", "op": "or"},
            {"value": "Lien", "op": "and_not"},
        ]
        sql, params = build_legacy_terms_sql(terms, "s.heading")
        assert sql == (
            "(s.heading ILIKE ? ESCAPE '\\' "
            "OR s.heading ILIKE ? ESCAPE '\\' "
            "AND s.heading NOT ILIKE ? ESCAPE '\\')"
        )
        assert params == ["Indebtedness", "Debt", "Lien"]

    def test_and_terms(self) -> None:
        terms = [
            {"value": "Restriction", "op": "or"},
            {"value": "Payment", "op": "and"},
        ]
        sql, params = build_legacy_terms_sql(terms, "s.heading")
        assert sql == (
            "(s.heading ILIKE ? ESCAPE '\\' "
            "AND s.heading ILIKE ? ESCAPE '\\')"
        )
        assert params == ["Restriction", "Payment"]

    def test_not_term(self) -> None:
        terms = [
            {"value": "Liens", "op": "or"},
            {"value": "Pledge", "op": "not"},
        ]
        sql, params = build_legacy_terms_sql(terms, "s.heading")
        assert sql == (
            "(s.heading ILIKE ? ESCAPE '\\' "
            "AND s.heading NOT ILIKE ? ESCAPE '\\')"
        )
        assert params == ["Liens", "Pledge"]

    def test_wrap_wildcards(self) -> None:
        terms = [
            {"value": "incur", "op": "or"},
            {"value": "Debt", "op": "or"},
        ]
        sql, params = build_legacy_terms_sql(terms, "c.text", wrap_wildcards=True)
        assert params == ["%incur%", "%Debt%"]
        assert "ILIKE" in sql

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            build_legacy_terms_sql([], "s.heading")

    def test_default_op_is_or(self) -> None:
        """When op is omitted, default to 'or'."""
        terms = [{"value": "A"}, {"value": "B"}]
        sql, _ = build_legacy_terms_sql(terms, "s.heading")
        assert "OR" in sql


# ─────────────── filter_terms_to_expr (proper AST conversion) ──────────


class TestFilterTermsToExpr:
    def test_single_term(self) -> None:
        terms = [{"value": "Indebtedness"}]
        expr = filter_terms_to_expr(terms)
        assert isinstance(expr, FilterMatch)
        assert expr.value == "Indebtedness"

    def test_two_or_terms_produce_or_group(self) -> None:
        terms = [{"value": "A", "op": "or"}, {"value": "B", "op": "or"}]
        expr = filter_terms_to_expr(terms)
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "or"
        assert len(expr.children) == 2

    def test_or_then_not_groups_correctly(self) -> None:
        """[A:or, B:or, C:and_not] → AND(OR(A,B), NOT C)."""
        terms = [
            {"value": "A", "op": "or"},
            {"value": "B", "op": "or"},
            {"value": "C", "op": "and_not"},
        ]
        expr = filter_terms_to_expr(terms)
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"
        # First child should be OR group of A, B
        or_child = expr.children[0]
        assert isinstance(or_child, FilterGroup)
        assert or_child.operator == "or"
        # Second child should be negated C
        not_child = expr.children[1]
        assert isinstance(not_child, FilterMatch)
        assert not_child.negate is True

    def test_and_term(self) -> None:
        terms = [{"value": "X", "op": "or"}, {"value": "Y", "op": "and"}]
        expr = filter_terms_to_expr(terms)
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"

    def test_or_run_split_by_and_then_or(self) -> None:
        """[A:or, B:and, C:or] flushes OR run before/after AND boundaries."""
        terms = [
            {"value": "A", "op": "or"},
            {"value": "B", "op": "and"},
            {"value": "C", "op": "or"},
        ]
        expr = filter_terms_to_expr(terms)
        assert isinstance(expr, FilterGroup)
        assert expr.operator == "and"
        assert len(expr.children) == 3
        assert all(isinstance(child, FilterMatch) for child in expr.children)
        sql, params = build_filter_sql(expr, "s.heading")
        assert sql == (
            "(s.heading ILIKE ? ESCAPE '\\' AND "
            "s.heading ILIKE ? ESCAPE '\\' AND "
            "s.heading ILIKE ? ESCAPE '\\')"
        )
        assert params == ["A", "B", "C"]

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            filter_terms_to_expr([])

    def test_result_is_valid_filter_expression(self) -> None:
        """Ensure all conversions produce valid FilterExpression types."""
        cases = [
            [{"value": "A"}],
            [{"value": "A"}, {"value": "B", "op": "or"}],
            [{"value": "A"}, {"value": "B", "op": "and"}],
            [{"value": "A"}, {"value": "B", "op": "not"}],
            [{"value": "A"}, {"value": "B", "op": "or"}, {"value": "C", "op": "and_not"}],
        ]
        for terms in cases:
            expr = filter_terms_to_expr(terms)
            assert isinstance(expr, (FilterMatch, FilterGroup))
            # And it should be compilable to SQL
            sql, params = build_filter_sql(expr, "col")
            assert len(params) == len(terms)

    def test_json_round_trip_after_conversion(self) -> None:
        """Terms → AST → JSON → AST round-trips."""
        terms = [
            {"value": "A", "op": "or"},
            {"value": "B", "op": "or"},
            {"value": "C", "op": "and_not"},
        ]
        expr = filter_terms_to_expr(terms)
        data = filter_expr_to_json(expr)
        restored = filter_expr_from_json(data)
        assert restored == expr


# ───────────────────────── Guardrails ──────────────────────────────────


class TestGuardrails:
    def test_valid_expression_no_errors(self) -> None:
        expr = FilterGroup(
            operator="or",
            children=(FilterMatch(value="A"), FilterMatch(value="B")),
        )
        errors = validate_filter_expr(expr)
        assert errors == []

    def test_max_depth_exceeded(self) -> None:
        """Build a chain of depth 6 — exceeds default max_depth=5."""
        inner: FilterMatch | FilterGroup = FilterMatch(value="deep")
        for _ in range(5):
            inner = FilterGroup(operator="and", children=(inner,))
        errors = validate_filter_expr(inner)
        assert any(e.code == "max_depth" for e in errors)

    def test_max_depth_at_limit_ok(self) -> None:
        """Depth exactly 5 should pass."""
        inner: FilterMatch | FilterGroup = FilterMatch(value="ok")
        for _ in range(4):
            inner = FilterGroup(operator="and", children=(inner,))
        errors = validate_filter_expr(inner)
        assert not any(e.code == "max_depth" for e in errors)

    def test_max_nodes_exceeded(self) -> None:
        """51 leaf nodes exceeds default max_nodes=50."""
        children = tuple(FilterMatch(value=f"v{i}") for i in range(51))
        expr = FilterGroup(operator="or", children=children)
        errors = validate_filter_expr(expr)
        assert any(e.code == "max_nodes" for e in errors)

    def test_max_nodes_at_limit_ok(self) -> None:
        children = tuple(FilterMatch(value=f"v{i}") for i in range(50))
        expr = FilterGroup(operator="or", children=children)
        errors = validate_filter_expr(expr)
        assert not any(e.code == "max_nodes" for e in errors)

    def test_max_wildcards_exceeded(self) -> None:
        """11 wildcard patterns exceeds default max_wildcards=10."""
        children = tuple(FilterMatch(value=f"%pattern{i}%") for i in range(11))
        expr = FilterGroup(operator="or", children=children)
        errors = validate_filter_expr(expr)
        assert any(e.code == "max_wildcards" for e in errors)

    def test_max_wildcards_at_limit_ok(self) -> None:
        children = tuple(FilterMatch(value=f"%pattern{i}%") for i in range(10))
        expr = FilterGroup(operator="or", children=children)
        errors = validate_filter_expr(expr)
        assert not any(e.code == "max_wildcards" for e in errors)

    def test_empty_group_error(self) -> None:
        expr = FilterGroup(operator="and", children=())
        errors = validate_filter_expr(expr)
        assert any(e.code == "empty_group" for e in errors)

    def test_empty_value_error(self) -> None:
        expr = FilterMatch(value="")
        errors = validate_filter_expr(expr)
        assert any(e.code == "empty_value" for e in errors)

    def test_invalid_operator_error(self) -> None:
        # Bypass frozen=True to create invalid state for testing
        expr = FilterGroup.__new__(FilterGroup)
        object.__setattr__(expr, "operator", "xor")
        object.__setattr__(expr, "children", (FilterMatch(value="x"),))
        errors = validate_filter_expr(expr)
        assert any(e.code == "invalid_operator" for e in errors)

    def test_custom_limits(self) -> None:
        children = tuple(FilterMatch(value=f"v{i}") for i in range(6))
        expr = FilterGroup(operator="or", children=children)
        errors = validate_filter_expr(expr, max_nodes=5)
        assert any(e.code == "max_nodes" for e in errors)

    def test_regex_counted_as_wildcard(self) -> None:
        """Regex patterns /pattern/ are counted toward the wildcard limit."""
        children = tuple(FilterMatch(value=f"/pattern{i}/") for i in range(11))
        expr = FilterGroup(operator="or", children=children)
        errors = validate_filter_expr(expr)
        assert any(e.code == "max_wildcards" for e in errors)

    def test_multiple_errors_returned(self) -> None:
        """Multiple guardrail violations reported simultaneously."""
        children = tuple(FilterMatch(value=f"%w{i}%") for i in range(51))
        expr = FilterGroup(operator="or", children=children)
        errors = validate_filter_expr(expr)
        codes = {e.code for e in errors}
        assert "max_nodes" in codes
        assert "max_wildcards" in codes

    def test_error_has_path(self) -> None:
        """Structural errors include dot-path to the problem node."""
        expr = FilterGroup(
            operator="or",
            children=(FilterMatch(value="ok"), FilterMatch(value="")),
        )
        errors = validate_filter_expr(expr)
        empty_errors = [e for e in errors if e.code == "empty_value"]
        assert len(empty_errors) == 1
        assert empty_errors[0].path == "children.1"

    def test_validation_error_is_frozen(self) -> None:
        """FilterValidationError uses frozen dataclass."""
        err = FilterValidationError(code="test", message="test msg")
        with pytest.raises(AttributeError):
            err.code = "changed"  # type: ignore[misc]


# ───────────────────── Metadata filter SQL ─────────────────────────────


class TestMetaFilterSql:
    def test_numeric_greater_than(self) -> None:
        meta = MetaFilterNumeric(field="facility_size_mm", operator=">", value=500.0)
        sql, params = build_meta_filter_sql(meta)
        assert sql == "d.facility_size_mm > ?"
        assert params == [500.0]

    def test_numeric_equals(self) -> None:
        meta = MetaFilterNumeric(field="vintage", operator="=", value=2024.0)
        sql, params = build_meta_filter_sql(meta)
        assert sql == "EXTRACT(YEAR FROM d.filing_date) = ?"
        assert params == [2024.0]

    def test_numeric_less_equal(self) -> None:
        meta = MetaFilterNumeric(field="facility_size_mm", operator="<=", value=1000.0)
        sql, params = build_meta_filter_sql(meta)
        assert sql == "d.facility_size_mm <= ?"
        assert params == [1000.0]

    def test_numeric_greater_equal(self) -> None:
        meta = MetaFilterNumeric(field="facility_size_mm", operator=">=", value=250.0)
        sql, params = build_meta_filter_sql(meta)
        assert sql == "d.facility_size_mm >= ?"
        assert params == [250.0]

    def test_numeric_less_than(self) -> None:
        meta = MetaFilterNumeric(field="vintage", operator="<", value=2020.0)
        sql, params = build_meta_filter_sql(meta)
        assert sql == "EXTRACT(YEAR FROM d.filing_date) < ?"
        assert params == [2020.0]

    def test_string_template(self) -> None:
        meta = MetaFilterString(
            field="template",
            expr=FilterMatch(value="kirkland"),
        )
        sql, params = build_meta_filter_sql(meta)
        assert sql == "d.template_family ILIKE ? ESCAPE '\\'"
        assert params == ["kirkland"]

    def test_string_or_group(self) -> None:
        meta = MetaFilterString(
            field="market",
            expr=FilterGroup(
                operator="or",
                children=(
                    FilterMatch(value="bsl"),
                    FilterMatch(value="broadly_syndicated"),
                ),
            ),
        )
        sql, params = build_meta_filter_sql(meta)
        assert "OR" in sql
        assert params == ["bsl", "broadly_syndicated"]

    def test_string_admin_agent(self) -> None:
        meta = MetaFilterString(
            field="admin_agent",
            expr=FilterMatch(value="JPMorgan"),
        )
        sql, params = build_meta_filter_sql(meta)
        assert "d.admin_agent" in sql

    def test_string_doc_type(self) -> None:
        meta = MetaFilterString(
            field="doc_type",
            expr=FilterMatch(value="credit_agreement"),
        )
        sql, params = build_meta_filter_sql(meta)
        assert "d.doc_type" in sql

    def test_unknown_field_raises(self) -> None:
        meta = MetaFilterNumeric(field="unknown_field", operator=">", value=1.0)
        with pytest.raises(ValueError, match="Unknown metadata field"):
            build_meta_filter_sql(meta)

    def test_invalid_numeric_op_raises(self) -> None:
        meta = MetaFilterNumeric(field="facility_size_mm", operator="LIKE", value=1.0)
        with pytest.raises(ValueError, match="Invalid numeric operator"):
            build_meta_filter_sql(meta)


# ───────────────────── Meta filter JSON round-trip ─────────────────────


class TestMetaFilterJson:
    def test_numeric_round_trip(self) -> None:
        meta = MetaFilterNumeric(field="facility_size_mm", operator=">", value=500.0)
        data = meta_filter_to_json(meta)
        assert data == {
            "type": "numeric",
            "field": "facility_size_mm",
            "operator": ">",
            "value": 500.0,
        }
        restored = meta_filter_from_json(data)
        assert restored == meta

    def test_string_round_trip(self) -> None:
        meta = MetaFilterString(
            field="template",
            expr=FilterMatch(value="kirkland"),
        )
        data = meta_filter_to_json(meta)
        restored = meta_filter_from_json(data)
        assert restored == meta


# ───────────────────── Query cost estimation ──────────────────────────


class TestQueryCost:
    def test_single_leaf(self) -> None:
        assert estimate_query_cost(FilterMatch(value="A")) == 1

    def test_wildcard_adds_cost(self) -> None:
        cost = estimate_query_cost(FilterMatch(value="%pattern%"))
        assert cost == 3  # 1 base + 2 wildcard

    def test_regex_adds_cost(self) -> None:
        cost = estimate_query_cost(FilterMatch(value="/indebt.*/"))
        assert cost == 4  # 1 base + 3 regex

    def test_group_adds_overhead(self) -> None:
        expr = FilterGroup(
            operator="or",
            children=(FilterMatch(value="A"), FilterMatch(value="B")),
        )
        cost = estimate_query_cost(expr)
        assert cost == 3  # 1 group + 1 + 1

    def test_nested_groups(self) -> None:
        inner = FilterGroup(
            operator="or",
            children=(FilterMatch(value="A"), FilterMatch(value="B")),
        )
        outer = FilterGroup(operator="and", children=(inner, FilterMatch(value="C")))
        cost = estimate_query_cost(outer)
        assert cost == 5  # outer(1) + inner(1+1+1) + C(1)


# ──────────── build_multi_field_sql ────────────────────────────────────


class TestBuildMultiFieldSql:
    def test_empty_fields(self) -> None:
        where, params, joins = build_multi_field_sql({})
        assert where == "1=1"
        assert params == []
        assert joins == set()

    def test_heading_only(self) -> None:
        fields = {"heading": FilterMatch(value="Indebtedness")}
        where, params, joins = build_multi_field_sql(fields)
        assert "s.heading ILIKE" in where
        assert len(params) == 1
        assert "%Indebtedness%" in params[0]
        assert joins == set()

    def test_article_adds_join(self) -> None:
        fields = {"article": FilterMatch(value="negative covenants")}
        where, params, joins = build_multi_field_sql(fields)
        assert "a.title ILIKE" in where
        assert "CAST(s.article_num AS VARCHAR)" in where
        assert len(joins) == 1
        assert any("JOIN articles" in j for j in joins)

    def test_clause_subquery(self) -> None:
        fields = {"clause": FilterMatch(value="indebtedness")}
        where, params, joins = build_multi_field_sql(fields)
        assert "EXISTS" in where
        assert "clauses" in where
        assert "c.header_text ILIKE" in where
        assert joins == set()

    def test_defined_term_subquery(self) -> None:
        fields = {"defined_term": FilterMatch(value="Permitted Liens")}
        where, params, joins = build_multi_field_sql(fields)
        assert "EXISTS" in where
        assert "definitions" in where
        assert "d.term ILIKE" in where

    def test_section_filter(self) -> None:
        fields = {"section": FilterMatch(value="7.01")}
        where, params, joins = build_multi_field_sql(fields)
        assert "s.section_number ILIKE" in where
        assert params == ["7.01"]

    def test_multi_field_combined(self) -> None:
        fields = {
            "heading": FilterMatch(value="debt"),
            "article": FilterMatch(value="negative covenants"),
        }
        where, params, joins = build_multi_field_sql(fields)
        assert "s.heading ILIKE" in where
        assert "a.title ILIKE" in where
        assert " AND " in where
        assert len(joins) == 1

    def test_or_group_heading(self) -> None:
        fields = {
            "heading": FilterGroup(
                operator="or",
                children=(FilterMatch(value="A"), FilterMatch(value="B")),
            ),
        }
        where, params, joins = build_multi_field_sql(fields)
        assert " OR " in where
        assert len(params) == 2
