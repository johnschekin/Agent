"""AST-based filter expression system for SQL query generation.

Replaces the flat ``FilterTerm[]`` approach in ``server.py:_build_filter_group()``
with a recursive AST supporting proper AND/OR/NOT precedence and arbitrary nesting.

Two node types:

* **FilterMatch** (leaf) — single ILIKE match, optionally negated.
* **FilterGroup** (compound) — AND/OR of children.

Functions:

* ``build_filter_sql``  — recursive SQL generation with correct parenthesisation.
* ``filter_expr_from_json`` / ``filter_expr_to_json`` — JSON round-trip.
* ``filter_terms_to_expr`` — convert legacy ``FilterTerm[]`` to proper AST.
* ``build_legacy_terms_sql`` — backward-compat: identical SQL to old ``_build_filter_group()``.
* ``escape_like`` — escape ``%`` and ``_`` for ILIKE literals.
* ``validate_filter_expr`` — guardrails (depth, node count, wildcard count).
* ``build_meta_filter_sql`` — SQL generation for metadata field filters.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FilterMatch:
    """Leaf: single ILIKE match against a column."""

    value: str
    negate: bool = False


@dataclass(frozen=True, slots=True)
class FilterGroup:
    """Compound: AND/OR of children (FilterMatch | FilterGroup)."""

    operator: str  # "and" | "or"
    children: tuple[FilterMatch | FilterGroup, ...]


FilterExpression = FilterMatch | FilterGroup


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FilterValidationError:
    """Structured error from filter expression validation."""

    code: str  # "max_depth" | "max_nodes" | "max_wildcards" | "empty_group" | "invalid_operator"
    message: str
    path: str = ""  # dot-separated path into AST (e.g., "children.0.children.1")


# ---------------------------------------------------------------------------
# Guardrail constants
# ---------------------------------------------------------------------------

MAX_AST_DEPTH = 5
MAX_AST_NODES = 50
MAX_WILDCARDS = 10


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------

def escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcards so ``%`` and ``_`` match literally.

    Uses backslash as escape character (pair with ``ESCAPE '\\\\'`` in SQL).
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_filter_sql(
    expr: FilterExpression,
    column: str,
    *,
    wrap_wildcards: bool = False,
) -> tuple[str, list[str]]:
    """Compile *expr* into a parenthesised SQL fragment + parameter list.

    Parameters
    ----------
    expr:
        The filter AST to compile.
    column:
        Fully-qualified column reference (e.g. ``"s.heading"``).
    wrap_wildcards:
        If ``True``, wraps each match value in ``%…%`` for contains-style matching.

    Returns
    -------
    tuple[str, list[str]]
        ``(sql_fragment, params)`` where *sql_fragment* is a parenthesised
        boolean expression and *params* are the positional ``?`` bind values.
    """
    if isinstance(expr, FilterMatch):
        return _match_to_sql(expr, column, wrap_wildcards=wrap_wildcards)
    # FilterGroup
    if not expr.children:
        # Degenerate empty group — vacuously true
        return ("(1=1)", [])

    parts: list[str] = []
    params: list[str] = []
    joiner = " AND " if expr.operator == "and" else " OR "

    for child in expr.children:
        child_sql, child_params = build_filter_sql(
            child, column, wrap_wildcards=wrap_wildcards
        )
        parts.append(child_sql)
        params.extend(child_params)

    return ("(" + joiner.join(parts) + ")", params)


def _match_to_sql(
    match: FilterMatch,
    column: str,
    *,
    wrap_wildcards: bool = False,
) -> tuple[str, list[str]]:
    """Generate SQL for a single FilterMatch leaf."""
    val = match.value
    if wrap_wildcards:
        escaped = escape_like(val)
        val = f"%{escaped}%"

    sql = (
        f"{column} NOT ILIKE ? ESCAPE '\\'"
        if match.negate
        else f"{column} ILIKE ? ESCAPE '\\'"
    )
    return (sql, [val])


# ---------------------------------------------------------------------------
# Backward-compat: legacy FilterTerm[] → identical SQL
# ---------------------------------------------------------------------------

def build_legacy_terms_sql(
    terms: list[dict[str, Any]],
    column: str,
    *,
    wrap_wildcards: bool = False,
) -> tuple[str, list[str]]:
    """Generate SQL identical to the old ``_build_filter_group()``.

    This function exists solely for backward compatibility during migration.
    It reproduces the flat, un-grouped SQL fragment that the original
    ``server.py:_build_filter_group()`` produced, including its intentional
    lack of operator-precedence grouping.

    For new code, use ``build_filter_sql()`` with a proper ``FilterExpression``
    AST instead.
    """
    if not terms:
        raise ValueError("Cannot build filter SQL from empty term list")

    parts: list[str] = []
    params: list[str] = []

    for i, term in enumerate(terms):
        val = term["value"]
        if wrap_wildcards:
            escaped = escape_like(val)
            val = f"%{escaped}%"

        if i == 0:
            parts.append(f"{column} ILIKE ? ESCAPE '\\'")
        else:
            op = term.get("op", "or").lower()
            if op in ("not", "and_not"):
                parts.append(f"AND {column} NOT ILIKE ? ESCAPE '\\'")
            elif op == "and":
                parts.append(f"AND {column} ILIKE ? ESCAPE '\\'")
            else:  # "or" or default
                parts.append(f"OR {column} ILIKE ? ESCAPE '\\'")
        params.append(val)

    return ("(" + " ".join(parts) + ")", params)


def filter_terms_to_expr(terms: list[dict[str, Any]]) -> FilterExpression:
    """Convert legacy ``FilterTerm[]`` (from server.py) to a proper FilterExpression AST.

    The legacy format is a list of ``{"value": str, "op": str}`` dicts where
    ``op`` is one of ``"or"``, ``"and"``, ``"not"``, ``"and_not"``.

    The conversion groups consecutive OR terms into OR groups, then ANDs
    everything together.  This produces *properly parenthesised* SQL that is
    semantically correct (unlike the legacy flat format which had precedence
    ambiguities).

    For identical-to-legacy SQL output, use ``build_legacy_terms_sql()`` instead.
    """
    if not terms:
        raise ValueError("Cannot convert empty FilterTerm list to FilterExpression")

    if len(terms) == 1:
        return FilterMatch(value=terms[0]["value"])

    # Group consecutive OR terms, then AND everything together.
    # E.g., [A:or, B:or, C:and_not, D:and] →
    #   FilterGroup(and, [FilterGroup(or, [A, B]), FilterMatch(C, negate=True), D])
    and_parts: list[FilterExpression] = []
    or_run: list[FilterMatch] = []

    for i, term in enumerate(terms):
        val = term["value"]
        op = term.get("op", "or").lower() if i > 0 else "or"

        if op == "or":
            or_run.append(FilterMatch(value=val))
        else:
            # Flush any pending OR run
            if or_run:
                if len(or_run) == 1:
                    and_parts.append(or_run[0])
                else:
                    and_parts.append(FilterGroup(operator="or", children=tuple(or_run)))
                or_run = []

            if op in ("not", "and_not"):
                and_parts.append(FilterMatch(value=val, negate=True))
            else:  # "and"
                and_parts.append(FilterMatch(value=val))

    # Flush trailing OR run
    if or_run:
        if len(or_run) == 1:
            and_parts.append(or_run[0])
        else:
            and_parts.append(FilterGroup(operator="or", children=tuple(or_run)))

    if len(and_parts) == 1:
        return and_parts[0]
    return FilterGroup(operator="and", children=tuple(and_parts))


# ---------------------------------------------------------------------------
# Metadata field SQL generation
# ---------------------------------------------------------------------------

# Metadata fields that support numeric comparison operators
_NUMERIC_META_FIELDS: frozenset[str] = frozenset({
    "facility_size_mm",
    "vintage",
})

# Metadata fields that use ILIKE string matching
_STRING_META_FIELDS: frozenset[str] = frozenset({
    "template",
    "market",
    "doc_type",
    "admin_agent",
})

# All valid metadata fields
VALID_META_FIELDS: frozenset[str] = _NUMERIC_META_FIELDS | _STRING_META_FIELDS

# Mapping from DSL meta field names to actual SQL column references
META_FIELD_COLUMN_MAP: dict[str, str] = {
    "template": "d.template_family",
    "vintage": "EXTRACT(YEAR FROM d.filing_date)",
    "market": "d.market_segment",
    "doc_type": "d.doc_type",
    "admin_agent": "d.admin_agent",
    "facility_size_mm": "d.facility_size_mm",
}

# Valid numeric comparison operators
_NUMERIC_OPS: frozenset[str] = frozenset({">", "<", ">=", "<=", "="})


@dataclass(frozen=True, slots=True)
class MetaFilterNumeric:
    """Numeric comparison against a metadata column."""

    field: str       # e.g. "facility_size_mm"
    operator: str    # ">" | "<" | ">=" | "<=" | "="
    value: float


@dataclass(frozen=True, slots=True)
class MetaFilterString:
    """ILIKE string match against a metadata column."""

    field: str       # e.g. "template"
    expr: FilterExpression  # AST of ILIKE matches


MetaFilter = MetaFilterNumeric | MetaFilterString


def build_meta_filter_sql(meta: MetaFilter) -> tuple[str, list[Any]]:
    """Compile a metadata filter into a SQL fragment + parameters.

    Returns
    -------
    tuple[str, list[Any]]
        ``(sql_fragment, params)`` ready to inject into a WHERE clause.
    """
    column = META_FIELD_COLUMN_MAP.get(meta.field)
    if column is None:
        raise ValueError(f"Unknown metadata field: {meta.field!r}")

    if isinstance(meta, MetaFilterNumeric):
        if meta.operator not in _NUMERIC_OPS:
            raise ValueError(f"Invalid numeric operator: {meta.operator!r}")
        sql = f"{column} {meta.operator} ?"
        return (sql, [meta.value])

    # MetaFilterString — delegate to build_filter_sql
    return build_filter_sql(meta.expr, column)


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------

def filter_expr_to_json(expr: FilterExpression) -> dict[str, Any]:
    """Serialize a FilterExpression AST to a JSON-compatible dict.

    Leaf (FilterMatch)::

        {"value": "Indebtedness"}
        {"value": "Lien", "negate": true}

    Group (FilterGroup)::

        {"op": "and", "children": [...]}
    """
    if isinstance(expr, FilterMatch):
        d: dict[str, Any] = {"value": expr.value}
        if expr.negate:
            d["negate"] = True
        return d
    # FilterGroup
    return {
        "op": expr.operator,
        "children": [filter_expr_to_json(c) for c in expr.children],
    }


def filter_expr_from_json(
    data: Any,
    *,
    max_depth: int = MAX_AST_DEPTH,
    max_nodes: int = MAX_AST_NODES,
    max_wildcards: int = MAX_WILDCARDS,
) -> FilterExpression:
    """Deserialize a JSON dict into a FilterExpression AST.

    Recognises two shapes:

    * Leaf: ``{"value": "..."}`` or ``{"value": "...", "negate": true}``
    * Group: ``{"op": "and"|"or", "children": [...]}``

    Raises ``ValueError`` on malformed input.
    """
    if not isinstance(data, dict):
        raise ValueError("Filter expression payload must be an object")

    nodes_seen = 0
    wildcard_seen = 0

    def _parse(node: Any, depth: int) -> FilterExpression:
        nonlocal nodes_seen, wildcard_seen

        if depth > max_depth:
            raise ValueError(f"AST depth {depth} exceeds maximum {max_depth}")
        if not isinstance(node, dict):
            raise ValueError("Filter expression node must be an object")

        # Legacy shape support:
        # - {"type":"match","value":"..."}
        # - {"type":"group","operator":"or","children":[...]}
        node_type = str(node.get("type", "")).lower()
        op_value = node.get("op", node.get("operator"))

        if "value" in node or node_type == "match":
            val = str(node.get("value", ""))
            nodes_seen += 1
            if nodes_seen > max_nodes:
                raise ValueError(f"AST has {nodes_seen} nodes, maximum is {max_nodes}")
            if _is_wildcard_or_regex_value(val):
                wildcard_seen += 1
                if wildcard_seen > max_wildcards:
                    raise ValueError(
                        "AST has "
                        f"{wildcard_seen} wildcard/regex patterns, maximum is {max_wildcards}"
                    )
            return FilterMatch(
                value=val,
                negate=bool(node.get("negate", False)),
            )

        if op_value is not None or node_type == "group":
            op = str(op_value).lower()
            if op not in ("and", "or"):
                raise ValueError(f"Invalid filter group operator: {op!r} (expected 'and' or 'or')")
            raw_children = node.get("children")
            if not isinstance(raw_children, list):
                raise ValueError("FilterGroup 'children' must be a list")
            children = tuple(_parse(c, depth + 1) for c in raw_children)
            return FilterGroup(operator=op, children=children)

        raise ValueError(f"Unrecognised filter expression shape: {sorted(node.keys())}")

    return _parse(data, 1)


def meta_filter_to_json(meta: MetaFilter) -> dict[str, Any]:
    """Serialize a MetaFilter to a JSON-compatible dict."""
    if isinstance(meta, MetaFilterNumeric):
        return {
            "type": "numeric",
            "field": meta.field,
            "operator": meta.operator,
            "value": meta.value,
        }
    return {
        "type": "string",
        "field": meta.field,
        "expr": filter_expr_to_json(meta.expr),
    }


def meta_filter_from_json(data: dict[str, Any]) -> MetaFilter:
    """Deserialize a JSON dict into a MetaFilter."""
    typ = data.get("type", "string")
    field = str(data["field"])
    if typ == "numeric":
        return MetaFilterNumeric(
            field=field,
            operator=str(data["operator"]),
            value=float(data["value"]),
        )
    return MetaFilterString(
        field=field,
        expr=filter_expr_from_json(data["expr"]),
    )


# ---------------------------------------------------------------------------
# AST validation / guardrails
# ---------------------------------------------------------------------------

def validate_filter_expr(
    expr: FilterExpression,
    *,
    max_depth: int = MAX_AST_DEPTH,
    max_nodes: int = MAX_AST_NODES,
    max_wildcards: int = MAX_WILDCARDS,
) -> list[FilterValidationError]:
    """Validate guardrail constraints on *expr*.

    Returns a (possibly empty) list of ``FilterValidationError``.
    Does NOT raise — callers decide whether errors are fatal.
    """
    errors: list[FilterValidationError] = []
    node_count = _count_nodes(expr)
    if node_count > max_nodes:
        errors.append(FilterValidationError(
            code="max_nodes",
            message=f"AST has {node_count} nodes, maximum is {max_nodes}",
        ))
    depth = _measure_depth(expr)
    if depth > max_depth:
        errors.append(FilterValidationError(
            code="max_depth",
            message=f"AST depth is {depth}, maximum is {max_depth}",
        ))
    wildcard_count = _count_wildcards(expr)
    if wildcard_count > max_wildcards:
        errors.append(FilterValidationError(
            code="max_wildcards",
            message=f"AST has {wildcard_count} wildcard/regex patterns, maximum is {max_wildcards}",
        ))
    _validate_structure(expr, errors, "")
    return errors


def _count_nodes(expr: FilterExpression) -> int:
    """Count total leaf nodes in the AST."""
    if isinstance(expr, FilterMatch):
        return 1
    return sum(_count_nodes(c) for c in expr.children)


def _measure_depth(expr: FilterExpression) -> int:
    """Measure maximum nesting depth.  A single leaf = depth 1."""
    if isinstance(expr, FilterMatch):
        return 1
    if not expr.children:
        return 1
    return 1 + max(_measure_depth(c) for c in expr.children)


def _count_wildcards(expr: FilterExpression) -> int:
    """Count leaf nodes whose value contains SQL wildcards or regex patterns."""
    if isinstance(expr, FilterMatch):
        return 1 if _is_wildcard_or_regex_value(expr.value) else 0
    return sum(_count_wildcards(c) for c in expr.children)


def _is_wildcard_or_regex_value(value: str) -> bool:
    """Return True when a leaf value represents wildcard or regex matching."""
    has_wildcard = bool(re.search(r'(?<!\\)[%_]', value))
    is_regex = len(value) >= 2 and value.startswith("/") and value.endswith("/")
    return has_wildcard or is_regex


def _validate_structure(
    expr: FilterExpression,
    errors: list[FilterValidationError],
    path: str,
) -> None:
    """Recursively check for structural issues."""
    if isinstance(expr, FilterMatch):
        if not expr.value:
            errors.append(FilterValidationError(
                code="empty_value",
                message="FilterMatch has empty value",
                path=path,
            ))
        return
    # FilterGroup
    if expr.operator not in ("and", "or"):
        errors.append(FilterValidationError(
            code="invalid_operator",
            message=f"Invalid operator {expr.operator!r} (expected 'and' or 'or')",
            path=path,
        ))
    if not expr.children:
        errors.append(FilterValidationError(
            code="empty_group",
            message="FilterGroup has no children",
            path=path,
        ))
    for i, child in enumerate(expr.children):
        child_path = f"{path}.children.{i}" if path else f"children.{i}"
        _validate_structure(child, errors, child_path)


# ---------------------------------------------------------------------------
# Utility: query cost estimation
# ---------------------------------------------------------------------------

def estimate_query_cost(expr: FilterExpression) -> int:
    """Return a weighted cost estimate for the filter expression.

    Cost weighting:
    * Each leaf node: 1
    * Each wildcard pattern: +2
    * Each regex pattern: +3
    * Each group level: +1

    Used by DSL guardrails to warn before expensive queries.
    """
    return _compute_cost(expr, 0)


def _compute_cost(expr: FilterExpression, depth: int) -> int:
    """Recursively compute query cost."""
    if isinstance(expr, FilterMatch):
        cost = 1
        if re.search(r'(?<!\\)[%_]', expr.value):
            cost += 2  # wildcard penalty
        if len(expr.value) >= 2 and expr.value.startswith("/") and expr.value.endswith("/"):
            cost += 3  # regex penalty
        return cost
    # FilterGroup
    group_cost = 1  # group overhead
    for child in expr.children:
        group_cost += _compute_cost(child, depth + 1)
    return group_cost


# ---------------------------------------------------------------------------
# Multi-field SQL builder (used by DSL-driven queries)
# ---------------------------------------------------------------------------

def build_multi_field_sql(
    text_fields: Mapping[str, FilterExpression],
    meta_filters: Mapping[str, Any] | None = None,
) -> tuple[str, list[Any], set[str]]:
    """Build SQL WHERE clauses from parsed DSL text fields + meta filters.

    Parameters
    ----------
    text_fields:
        Mapping of DSL field names to their parsed ``FilterExpression`` ASTs.
        Supported fields: ``heading``, ``article``, ``clause``, ``section``,
        ``defined_term``.
    meta_filters:
        Optional mapping of metadata field names to ``MetaFilter`` objects.

    Returns
    -------
    tuple[str, list[Any], set[str]]
        ``(where_clause, params, required_joins)`` where:
        - *where_clause* is a SQL fragment (without leading ``WHERE``),
        - *params* are the positional ``?`` bind values,
        - *required_joins* is a set of join clause strings the caller must add.

        Returns ``("1=1", [], set())`` when no fields are provided.
    """
    where_parts: list[str] = []
    params: list[Any] = []
    joins: set[str] = set()

    # heading: → s.heading ILIKE ?
    heading_expr = text_fields.get("heading")
    if heading_expr is not None:
        sql, p = build_filter_sql(heading_expr, "s.heading", wrap_wildcards=True)
        where_parts.append(sql)
        params.extend(p)

    # article: → match title OR article_num (requires JOIN articles a)
    article_expr = text_fields.get("article")
    if article_expr is not None:
        title_sql, title_p = build_filter_sql(
            article_expr, "a.title", wrap_wildcards=True,
        )
        num_sql, num_p = build_filter_sql(
            article_expr, "CAST(s.article_num AS VARCHAR)", wrap_wildcards=False,
        )
        where_parts.append(f"({title_sql} OR {num_sql})")
        params.extend(title_p)
        params.extend(num_p)
        joins.add(
            "JOIN articles a ON a.doc_id = s.doc_id AND a.article_num = s.article_num"
        )

    # section: → s.section_number ILIKE ?
    section_expr = text_fields.get("section")
    if section_expr is not None:
        sql, p = build_filter_sql(section_expr, "s.section_number")
        where_parts.append(sql)
        params.extend(p)

    # clause: → EXISTS subquery against clauses table
    clause_expr = text_fields.get("clause")
    if clause_expr is not None:
        inner_sql, inner_p = build_filter_sql(
            clause_expr, "c.header_text", wrap_wildcards=True,
        )
        where_parts.append(
            f"EXISTS (SELECT 1 FROM clauses c"
            f" WHERE c.doc_id = s.doc_id"
            f" AND c.section_number = s.section_number"
            f" AND {inner_sql})"
        )
        params.extend(inner_p)

    # defined_term: → EXISTS subquery against definitions table
    dt_expr = text_fields.get("defined_term")
    if dt_expr is not None:
        inner_sql, inner_p = build_filter_sql(
            dt_expr, "d.term", wrap_wildcards=True,
        )
        where_parts.append(
            f"EXISTS (SELECT 1 FROM definitions d"
            f" WHERE d.doc_id = s.doc_id"
            f" AND {inner_sql})"
        )
        params.extend(inner_p)

    # Meta filters (documents table conditions)
    if meta_filters:
        for _fname, meta in meta_filters.items():
            if hasattr(meta, "field"):
                meta_sql, meta_p = build_meta_filter_sql(meta)
                where_parts.append(meta_sql)
                params.extend(meta_p)

    if not where_parts:
        return ("1=1", [], set())

    return (" AND ".join(where_parts), params, joins)
