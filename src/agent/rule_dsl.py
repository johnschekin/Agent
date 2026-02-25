"""Text DSL parser for family link rules — backend single source of truth.

LexisNexis-style grammar with proximity operators, regex, ``@macro``
expansion, text fields and metadata fields.

Grammar (PEG-flavoured)::

    rule          := field_clause+
    field_clause  := FIELD_NAME ':' expr
    expr          := or_expr
    or_expr       := and_expr ('|' and_expr)*
    and_expr      := prox_expr ('&' prox_expr)*
    prox_expr     := not_expr (PROX_OP not_expr)?
    not_expr      := '!' not_expr | atom
    atom          := '(' expr ')' | REGEX | MACRO_REF | QUOTED_STRING | BARE_WORD
    FIELD_NAME    := TEXT_FIELD | META_FIELD
    TEXT_FIELD     := 'heading' | 'article' | 'clause' | 'section' | 'defined_term'
    META_FIELD     := 'template' | 'vintage' | 'market' | 'doc_type'
                    | 'admin_agent' | 'facility_size_mm'
    MACRO_REF     := '@' [a-z_][a-z0-9_]*
    PROX_OP       := '/s' | '/p' | '/' [0-9]+
    REGEX         := '/' [^/]+ '/'
    QUOTED_STRING := '"' [^"]* '"'
    BARE_WORD     := [^\\s&|!()"/]+

Public API:

* ``parse_dsl(text, macros)`` — parse DSL text into per-field AST dict.
* ``serialize_dsl(field_asts)`` — serialize per-field ASTs back to DSL text.
* ``validate_dsl(text, macros)`` — parse + validate, return structured result.
* ``expand_term_suggestions(term, ontology_synonyms, heading_cooccurrence)``
  — suggest synonym expansions for a term.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.query_filters import (
    FilterExpression,
    FilterGroup,
    FilterMatch,
    MetaFilter,
    MetaFilterNumeric,
    MetaFilterString,
    estimate_query_cost,
    validate_filter_expr,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEXT_FIELDS: frozenset[str] = frozenset({
    "heading", "article", "clause", "section", "defined_term",
})

META_FIELDS: frozenset[str] = frozenset({
    "template", "vintage", "market", "doc_type", "admin_agent", "facility_size_mm",
})

ALL_FIELDS: frozenset[str] = TEXT_FIELDS | META_FIELDS

# Fields that support proximity operators
_PROXIMITY_FIELDS: frozenset[str] = frozenset({"clause"})

# Guardrails
MAX_AST_DEPTH = 5
MAX_AST_NODES = 50
MAX_WILDCARDS = 10
MAX_QUERY_COST = 100


# ---------------------------------------------------------------------------
# AST node types (DSL-specific — wraps FilterExpression with proximity)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ProximityOp:
    """A proximity constraint between two sub-expressions.

    ``/s`` = same sentence, ``/p`` = same paragraph, ``/N`` = within N words.
    """

    left: FilterExpression
    right: FilterExpression
    kind: str   # "sentence" | "paragraph" | "words"
    distance: int = 0  # only meaningful when kind == "words"


@dataclass(frozen=True, slots=True)
class MacroRef:
    """A reference to a stored macro, resolved during parsing."""

    name: str


# ---------------------------------------------------------------------------
# Parse result
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DslParseError:
    """A single parse error with position information."""

    message: str
    position: int = 0    # character offset in source text
    field: str = ""      # which field clause, if known


@dataclass(frozen=True, slots=True)
class DslParseResult:
    """Result of parsing a DSL text string."""

    text_fields: dict[str, FilterExpression | ProximityOp]
    meta_fields: dict[str, MetaFilter]
    errors: list[DslParseError]
    normalized_text: str
    query_cost: int

    @property
    def ok(self) -> bool:
        """True if parsing succeeded with no errors."""
        return len(self.errors) == 0


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Token:
    """A single lexical token."""

    kind: str  # see _TOKEN_PATTERNS keys + "EOF"
    value: str
    pos: int


# Token patterns — order matters (first match wins)
_TOKEN_PATTERNS: list[tuple[str, str]] = [
    ("WHITESPACE", r"\s+"),
    ("FIELD_SEP", r":"),
    ("PIPE", r"\|"),
    ("AMP", r"&"),
    ("BANG", r"!"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("PROX_OP", r"/[sp](?![a-zA-Z0-9])"),   # /s or /p (not followed by alnum)
    ("PROX_N", r"/\d+"),                      # /5, /10, etc.
    ("REGEX", r"/[^/\s]+/"),                  # /pattern/
    ("NUMERIC_OP", r"[><=]{1,2}"),            # >, <, >=, <=, =
    ("MACRO_REF", r"@[a-z_][a-z0-9_]*"),     # @macro_name
    ("QUOTED_STRING", r'"[^"]*"'),            # "quoted string"
    ("BARE_WORD", r"[^\s&|!()\"/:@><=]+"),   # everything else
]

_COMPILED_PATTERNS = [(name, re.compile(pat)) for name, pat in _TOKEN_PATTERNS]


def _tokenize(text: str) -> list[_Token]:
    """Tokenize DSL text into a list of tokens."""
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        matched = False
        for name, pattern in _COMPILED_PATTERNS:
            m = pattern.match(text, pos)
            if m:
                if name != "WHITESPACE":
                    tokens.append(_Token(kind=name, value=m.group(), pos=pos))
                pos = m.end()
                matched = True
                break
        if not matched:
            # Unrecognised character — emit as error token and advance
            tokens.append(_Token(kind="ERROR", value=text[pos], pos=pos))
            pos += 1
    tokens.append(_Token(kind="EOF", value="", pos=pos))
    return tokens


# ---------------------------------------------------------------------------
# Recursive descent parser
# ---------------------------------------------------------------------------

class _Parser:
    """Recursive descent parser for the DSL grammar."""

    def __init__(
        self,
        tokens: list[_Token],
        macros: dict[str, FilterExpression | MacroRef],
        source_text: str,
    ) -> None:
        self._tokens = tokens
        self._macros = macros
        self._source = source_text
        self._pos = 0
        self._errors: list[DslParseError] = []
        self._macro_stack: list[str] = []  # circular reference detection

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        if self._pos < len(self._tokens) - 1:
            self._pos += 1
        return tok

    def _expect(self, kind: str) -> _Token | None:
        tok = self._peek()
        if tok.kind == kind:
            return self._advance()
        self._errors.append(DslParseError(
            message=f"Expected {kind}, got {tok.kind} ({tok.value!r})",
            position=tok.pos,
        ))
        return None

    def _error(self, msg: str, pos: int | None = None, field_name: str = "") -> None:
        self._errors.append(DslParseError(
            message=msg,
            position=pos if pos is not None else self._peek().pos,
            field=field_name,
        ))

    # ─── Alias helpers ─────────────────────────────────────────────

    _ALIASES: dict[str, str] = {"AND": "&", "OR": "|", "NOT": "!"}

    def _is_alias(self, alias: str) -> bool:
        """Check if the current token is a case-insensitive keyword alias."""
        tok = self._peek()
        return tok.kind == "BARE_WORD" and tok.value.upper() == alias

    def _suggest_for_unexpected(self, tok: _Token) -> str:
        """Return a helpful suffix suggestion for an unexpected token."""
        val = tok.value

        # Detect double operators like && or ||
        if val in ("&&", "||"):
            canonical = val[0]
            return f" (use single '{canonical}' instead of '{val}')"

        # Detect operator-like bare words
        upper = val.upper()
        if upper in self._ALIASES:
            canonical = self._ALIASES[upper]
            return f" ('{val}' is recognized as '{canonical}' — did you forget a left operand?)"

        # Detect close-match field names
        if tok.kind == "BARE_WORD" and ":" not in val:
            from difflib import get_close_matches
            close = get_close_matches(val.lower(), sorted(ALL_FIELDS), n=1, cutoff=0.6)
            if close:
                return f" — did you mean '{close[0]}'?"

            # Detect bare words that look like unquoted multi-word values
            # (a word right after a field's colon-delimited value)
            if self._pos > 0:
                prev = self._tokens[self._pos - 1]
                if prev.kind == "BARE_WORD" and prev.value not in ALL_FIELDS:
                    return " — multi-word values must be quoted (e.g. \"two words\")"

        return ""

    def _resolve_macro(
        self,
        macro_name: str,
        pos: int,
        field_name: str,
    ) -> FilterExpression | None:
        """Resolve macro references, including chained MacroRef indirection."""
        if macro_name in self._macro_stack:
            cycle = " -> ".join([*self._macro_stack, macro_name])
            self._error(
                f"Circular macro reference: {cycle}",
                pos,
                field_name,
            )
            return None
        if macro_name not in self._macros:
            self._error(
                f"Undefined macro: @{macro_name}",
                pos,
                field_name,
            )
            return None

        stack_start = len(self._macro_stack)
        self._macro_stack.append(macro_name)
        try:
            resolved: FilterExpression | MacroRef = self._macros[macro_name]
            while isinstance(resolved, MacroRef):
                next_name = resolved.name
                if next_name in self._macro_stack:
                    cycle = " -> ".join([*self._macro_stack, next_name])
                    self._error(
                        f"Circular macro reference: {cycle}",
                        pos,
                        field_name,
                    )
                    return None
                if next_name not in self._macros:
                    self._error(
                        f"Undefined macro: @{next_name}",
                        pos,
                        field_name,
                    )
                    return None
                self._macro_stack.append(next_name)
                resolved = self._macros[next_name]

            return resolved
        finally:
            del self._macro_stack[stack_start:]

    # ─── Top-level ────────────────────────────────────────────────

    def parse_rule(
        self,
    ) -> tuple[
        dict[str, FilterExpression | ProximityOp],
        dict[str, MetaFilter],
        list[DslParseError],
    ]:
        """Parse the full rule: one or more field_clause."""
        text_fields: dict[str, FilterExpression | ProximityOp] = {}
        meta_fields: dict[str, MetaFilter] = {}

        while self._peek().kind != "EOF":
            # Expect a field name (BARE_WORD that's a known field)
            tok = self._peek()
            if tok.kind == "ERROR":
                self._error(f"Unexpected character: {tok.value!r}", tok.pos)
                self._advance()
                continue

            if tok.kind != "BARE_WORD" or tok.value not in ALL_FIELDS:
                suggestion = self._suggest_for_unexpected(tok)
                self._error(
                    f"Expected field name (one of: {', '.join(sorted(ALL_FIELDS))}), "
                    f"got {tok.value!r}{suggestion}",
                    tok.pos,
                )
                self._advance()
                continue

            field_name = self._advance().value

            # Expect ':'
            sep = self._peek()
            if sep.kind == "FIELD_SEP":
                self._advance()
            elif sep.kind == "NUMERIC_OP" and field_name in META_FIELDS:
                # Meta fields with numeric comparison: `facility_size_mm > 500`
                pass  # Don't consume — the meta parser handles it
            else:
                self._error(f"Expected ':' after field name '{field_name}'", sep.pos)
                continue

            # Parse the expression for this field
            if field_name in META_FIELDS:
                meta_expr = self._parse_meta_field(field_name)
                if meta_expr is not None:
                    meta_fields[field_name] = meta_expr
            else:
                expr = self._parse_expr(field_name)
                if expr is not None:
                    text_fields[field_name] = expr

        return text_fields, meta_fields, self._errors

    # ─── Meta field parsing ───────────────────────────────────────

    def _parse_meta_field(self, field_name: str) -> MetaFilter | None:
        """Parse a metadata field clause.

        Handles:
        * Numeric comparisons: ``facility_size_mm > 500``
        * String matches: ``template: kirkland``
        * OR groups: ``market: (bsl | ig)``
        """
        tok = self._peek()

        # Numeric comparison: `> 500`, `= 2024`, etc.
        if tok.kind == "NUMERIC_OP":
            op = self._advance().value
            num_tok = self._peek()
            if num_tok.kind == "BARE_WORD":
                try:
                    val = float(self._advance().value)
                    return MetaFilterNumeric(field=field_name, operator=op, value=val)
                except ValueError:
                    self._error(
                        f"Expected numeric value after '{op}', got {num_tok.value!r}",
                        num_tok.pos,
                        field_name,
                    )
                    return None
            self._error(f"Expected numeric value after '{op}'", num_tok.pos, field_name)
            return None

        # String match — parse as FilterExpression and wrap
        expr = self._parse_or_expr(field_name)
        if expr is None:
            return None
        if isinstance(expr, ProximityOp):
            self._error(
                "Proximity operators are not supported in metadata fields",
                self._peek().pos,
                field_name,
            )
            return None
        return MetaFilterString(field=field_name, expr=expr)

    # ─── Expression parsing (recursive descent) ───────────────────

    def _parse_expr(
        self, field_name: str,
    ) -> FilterExpression | ProximityOp | None:
        """Parse an expression for a text field."""
        return self._parse_or_expr(field_name)

    def _parse_or_expr(
        self, field_name: str,
    ) -> FilterExpression | ProximityOp | None:
        """or_expr := and_expr ('|' and_expr)*"""
        left = self._parse_and_expr(field_name)
        if left is None:
            return None

        parts: list[FilterExpression | ProximityOp] = [left]
        while self._peek().kind == "PIPE" or self._is_alias("OR"):
            self._advance()
            right = self._parse_and_expr(field_name)
            if right is None:
                break
            parts.append(right)

        if len(parts) == 1:
            return parts[0]

        # Flatten into an OR group — but ProximityOp can't go inside FilterGroup
        # If any part is ProximityOp, that's an error
        filter_parts: list[FilterExpression] = []
        for p in parts:
            if isinstance(p, ProximityOp):
                self._error(
                    "Proximity operators cannot be combined with OR at the same level",
                    self._peek().pos,
                    field_name,
                )
                return None
            filter_parts.append(p)

        return FilterGroup(
            operator="or",
            children=tuple(filter_parts),
        )

    def _parse_and_expr(
        self, field_name: str,
    ) -> FilterExpression | ProximityOp | None:
        """and_expr := prox_expr ('&' prox_expr)*"""
        left = self._parse_prox_expr(field_name)
        if left is None:
            return None

        parts: list[FilterExpression | ProximityOp] = [left]
        while self._peek().kind == "AMP" or self._is_alias("AND"):
            self._advance()
            right = self._parse_prox_expr(field_name)
            if right is None:
                break
            parts.append(right)

        if len(parts) == 1:
            return parts[0]

        # Flatten — ProximityOp can't go inside FilterGroup directly
        filter_parts: list[FilterExpression] = []
        for p in parts:
            if isinstance(p, ProximityOp):
                self._error(
                    "Proximity operators cannot be combined with AND at the same level",
                    self._peek().pos,
                    field_name,
                )
                return None
            filter_parts.append(p)

        return FilterGroup(
            operator="and",
            children=tuple(filter_parts),
        )

    def _parse_prox_expr(
        self, field_name: str,
    ) -> FilterExpression | ProximityOp | None:
        """prox_expr := not_expr (PROX_OP not_expr)?"""
        left = self._parse_not_expr(field_name)
        if left is None:
            return None

        tok = self._peek()
        if tok.kind in ("PROX_OP", "PROX_N"):
            # Check field supports proximity
            if field_name not in _PROXIMITY_FIELDS:
                self._error(
                    f"Proximity operator '{tok.value}' is only valid on clause field "
                    f"(not '{field_name}')",
                    tok.pos,
                    field_name,
                )
                self._advance()  # consume the prox op to continue parsing
                # Still try to parse right side for error recovery
                self._parse_not_expr(field_name)
                return left

            prox_tok = self._advance()
            right = self._parse_not_expr(field_name)
            if right is None:
                return left

            # ProximityOp requires both sides to be FilterExpression
            if isinstance(left, ProximityOp) or isinstance(right, ProximityOp):
                self._error(
                    "Cannot chain proximity operators",
                    prox_tok.pos,
                    field_name,
                )
                return None

            if prox_tok.kind == "PROX_OP":
                kind = "sentence" if prox_tok.value == "/s" else "paragraph"
                return ProximityOp(left=left, right=right, kind=kind)
            else:
                # /N — extract number
                distance = int(prox_tok.value[1:])
                return ProximityOp(
                    left=left, right=right, kind="words", distance=distance,
                )

        return left

    def _parse_not_expr(
        self, field_name: str,
    ) -> FilterExpression | ProximityOp | None:
        """not_expr := '!' not_expr | atom"""
        if self._peek().kind == "BANG" or self._is_alias("NOT"):
            self._advance()
            inner = self._parse_not_expr(field_name)
            if inner is None:
                return None
            if isinstance(inner, ProximityOp):
                self._error(
                    "Cannot negate a proximity expression",
                    self._peek().pos,
                    field_name,
                )
                return None
            if isinstance(inner, FilterMatch):
                return FilterMatch(value=inner.value, negate=not inner.negate)
            # Negate a group — push negation to leaves via De Morgan's law
            # NOT (A OR B) = NOT A AND NOT B
            # NOT (A AND B) = NOT A OR NOT B
            negated_children: list[FilterMatch | FilterGroup] = []
            for child in inner.children:
                if isinstance(child, FilterMatch):
                    negated_children.append(
                        FilterMatch(value=child.value, negate=not child.negate)
                    )
                else:
                    # Subgroup — keep as-is (deeper negation would need recursion,
                    # but the user should explicitly negate at the leaf level)
                    negated_children.append(child)
            # Flip operator via De Morgan: NOT (A OR B) = NOT A AND NOT B
            flipped_op = "and" if inner.operator == "or" else "or"
            return FilterGroup(operator=flipped_op, children=tuple(negated_children))
        return self._parse_atom(field_name)

    def _parse_atom(
        self, field_name: str,
    ) -> FilterExpression | None:
        """atom := '(' expr ')' | REGEX | MACRO_REF | QUOTED_STRING | BARE_WORD"""
        tok = self._peek()

        # Parenthesised expression
        if tok.kind == "LPAREN":
            self._advance()
            inner = self._parse_or_expr(field_name)
            if self._peek().kind == "RPAREN":
                self._advance()
            else:
                self._error("Expected closing ')'", self._peek().pos, field_name)
            if inner is None:
                return None
            if isinstance(inner, ProximityOp):
                self._error(
                    "Proximity operators cannot be wrapped in parentheses at the "
                    "expression level; use them at top level of a field clause",
                    tok.pos,
                    field_name,
                )
                return None
            return inner

        # Regex: /pattern/
        if tok.kind == "REGEX":
            self._advance()
            pattern = tok.value[1:-1]  # strip delimiters
            # Validate regex syntax
            try:
                re.compile(pattern)
            except re.error as e:
                self._error(
                    f"Invalid regex pattern: {e}",
                    tok.pos,
                    field_name,
                )
                return None
            return FilterMatch(value=tok.value)  # keep /…/ delimiters as marker

        # Macro reference: @name
        if tok.kind == "MACRO_REF":
            self._advance()
            macro_name = tok.value[1:]  # strip @
            return self._resolve_macro(macro_name, tok.pos, field_name)

        # Quoted string: "…"
        if tok.kind == "QUOTED_STRING":
            self._advance()
            value = tok.value[1:-1]  # strip quotes
            return FilterMatch(value=value)

        # Bare word — but guard against aliases consumed as values
        if tok.kind == "BARE_WORD":
            if tok.value.upper() in self._ALIASES:
                self._error(
                    f"Unexpected operator '{tok.value}' — did you forget a left operand?",
                    tok.pos,
                    field_name,
                )
                self._advance()
                return None
            self._advance()
            return FilterMatch(value=tok.value)

        # Nothing matched — error
        if tok.kind != "EOF":
            suggestion = self._suggest_for_unexpected(tok)
            self._error(
                f"Unexpected token: {tok.value!r}{suggestion}",
                tok.pos,
                field_name,
            )
            self._advance()  # consume to avoid infinite loop
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dsl(
    text: str,
    macros: dict[str, FilterExpression | MacroRef] | None = None,
) -> DslParseResult:
    """Parse DSL text into per-field ASTs.

    Parameters
    ----------
    text:
        The DSL query text (e.g., ``"heading: Indebtedness & !Lien"``).
    macros:
        Optional dict mapping macro names to resolved AST subtrees (or
        ``MacroRef`` aliases to other macros).
        Used to expand ``@macro_name`` references.

    Returns
    -------
    DslParseResult
        Contains ``text_fields``, ``meta_fields``, ``errors``,
        ``normalized_text``, and ``query_cost``.
    """
    if macros is None:
        macros = {}

    tokens = _tokenize(text)
    parser = _Parser(tokens, macros, text)
    text_fields, meta_fields, errors = parser.parse_rule()

    # Compute normalized text
    normalized = serialize_dsl(text_fields, meta_fields)

    # Compute query cost
    cost = 0
    for expr in text_fields.values():
        if isinstance(expr, ProximityOp):
            cost += _proximity_cost(expr)
        else:
            cost += estimate_query_cost(expr)
    for mf in meta_fields.values():
        if isinstance(mf, MetaFilterString):
            cost += estimate_query_cost(mf.expr)
        else:
            cost += 1

    return DslParseResult(
        text_fields=text_fields,
        meta_fields=meta_fields,
        errors=errors,
        normalized_text=normalized,
        query_cost=cost,
    )


def _proximity_cost(prox: ProximityOp) -> int:
    """Cost estimate for a proximity expression."""
    base = 5  # proximity is expensive
    left_cost = estimate_query_cost(prox.left)
    right_cost = estimate_query_cost(prox.right)
    return base + left_cost + right_cost


def validate_dsl(
    text: str,
    macros: dict[str, FilterExpression | MacroRef] | None = None,
) -> DslParseResult:
    """Parse and validate DSL text.  Returns parse result with all guardrail errors.

    This is the primary entry point for the ``POST /api/links/rules/validate-dsl``
    endpoint.  The frontend sends raw text and receives the result.
    """
    result = parse_dsl(text, macros)

    # Additional guardrail checks on each text field AST
    all_errors = list(result.errors)
    for fname, expr in result.text_fields.items():
        if isinstance(expr, ProximityOp):
            # Check both sides of proximity
            for sub_expr, label in [(expr.left, "left"), (expr.right, "right")]:
                vr = validate_filter_expr(sub_expr)
                for e in vr:
                    all_errors.append(DslParseError(
                        message=f"[{fname}/{label}] {e.message}",
                        position=0,
                        field=fname,
                    ))
        else:
            vr = validate_filter_expr(expr)
            for e in vr:
                all_errors.append(DslParseError(
                    message=f"[{fname}] {e.message}",
                    position=0,
                    field=fname,
                ))

    # Query cost check
    if result.query_cost > MAX_QUERY_COST:
        all_errors.append(DslParseError(
            message=f"Query cost {result.query_cost} exceeds maximum {MAX_QUERY_COST}",
            position=0,
        ))

    if all_errors != list(result.errors):
        return DslParseResult(
            text_fields=result.text_fields,
            meta_fields=result.meta_fields,
            errors=all_errors,
            normalized_text=result.normalized_text,
            query_cost=result.query_cost,
        )
    return result


# ---------------------------------------------------------------------------
# Serializer: AST → DSL text
# ---------------------------------------------------------------------------

def serialize_dsl(
    text_fields: dict[str, FilterExpression | ProximityOp],
    meta_fields: dict[str, MetaFilter] | None = None,
) -> str:
    """Serialize per-field ASTs back to normalized DSL text.

    Round-trip: ``serialize_dsl(**parse_dsl(t).text_fields)`` normalizes ``t``.
    """
    parts: list[str] = []

    # Text fields first (in canonical order)
    for fname in ["heading", "article", "clause", "section", "defined_term"]:
        if fname not in text_fields:
            continue
        expr = text_fields[fname]
        serialized = _serialize_text_expr(expr)
        parts.append(f"{fname}: {serialized}")

    # Meta fields
    if meta_fields:
        for fname in [
            "template", "vintage", "market",
            "doc_type", "admin_agent", "facility_size_mm",
        ]:
            if fname not in meta_fields:
                continue
            meta = meta_fields[fname]
            serialized = _serialize_meta(meta)
            parts.append(f"{fname}{serialized}")

    return "\n".join(parts)


def _serialize_text_expr(expr: FilterExpression | ProximityOp) -> str:
    """Serialize a text field expression to DSL text."""
    if isinstance(expr, ProximityOp):
        left_str = _serialize_filter_expr(expr.left)
        right_str = _serialize_filter_expr(expr.right)
        if expr.kind == "sentence":
            return f"{left_str} /s {right_str}"
        elif expr.kind == "paragraph":
            return f"{left_str} /p {right_str}"
        else:
            return f"{left_str} /{expr.distance} {right_str}"
    return _serialize_filter_expr(expr)


def _serialize_filter_expr(expr: FilterExpression) -> str:
    """Serialize a FilterExpression to DSL text."""
    if isinstance(expr, FilterMatch):
        return _serialize_match(expr)
    # FilterGroup
    parts = [_serialize_filter_expr(c) for c in expr.children]
    joined = " | ".join(parts) if expr.operator == "or" else " & ".join(parts)

    # Wrap in parens if this is a group with multiple children
    # (avoids ambiguity in nested groups)
    if len(expr.children) > 1:
        return f"({joined})"
    return joined


def _serialize_match(match: FilterMatch) -> str:
    """Serialize a FilterMatch to DSL text."""
    val = match.value

    # Regex values (keep /…/ delimiters)
    if len(val) >= 2 and val.startswith("/") and val.endswith("/"):
        if match.negate:
            return f"!{val}"
        return val

    # Bare word (no spaces/special chars) vs quoted string
    needs_quoting = " " in val or any(c in val for c in '&|!()"/') or not val
    quoted = f'"{val}"' if needs_quoting else val

    if match.negate:
        return f"!{quoted}"
    return quoted


def _serialize_meta(meta: MetaFilter) -> str:
    """Serialize a metadata filter to DSL text."""
    if isinstance(meta, MetaFilterNumeric):
        return f" {meta.operator} {meta.value:g}"
    # MetaFilterString
    expr_str = _serialize_filter_expr(meta.expr)
    return f": {expr_str}"


# ---------------------------------------------------------------------------
# Term expansion suggestions
# ---------------------------------------------------------------------------

def expand_term_suggestions(
    term: str,
    *,
    ontology_synonyms: list[str] | None = None,
    heading_cooccurrence: list[str] | None = None,
) -> list[str]:
    """Suggest expansions for a term based on ontology synonyms and corpus stats.

    Returns a list of suggested terms (excluding the original).
    Used by ``POST /api/links/rules/expand-term``.
    """
    suggestions: list[str] = []
    seen: set[str] = {term.lower()}

    if ontology_synonyms:
        for syn in ontology_synonyms:
            if syn.lower() not in seen:
                suggestions.append(syn)
                seen.add(syn.lower())

    if heading_cooccurrence:
        for co in heading_cooccurrence:
            if co.lower() not in seen:
                suggestions.append(co)
                seen.add(co.lower())

    return suggestions


# ---------------------------------------------------------------------------
# Bidirectional conversion: heading AST ↔ full DSL
# ---------------------------------------------------------------------------

def dsl_from_heading_ast(ast_json: dict[str, Any]) -> str:
    """Convert a ``heading_filter_ast`` JSON dict to a DSL string.

    The returned string is a single ``heading:`` field clause, e.g.::

        heading: Indebtedness | "Limitation on Indebtedness"

    Returns an empty string if *ast_json* is empty or cannot be parsed.
    """
    if not ast_json:
        return ""
    from agent.query_filters import filter_expr_from_json  # noqa: F811

    try:
        expr = filter_expr_from_json(ast_json)
    except (ValueError, KeyError, TypeError):
        return ""
    return serialize_dsl({"heading": expr})


def heading_ast_from_dsl(dsl_text: str) -> dict[str, Any] | None:
    """Extract the ``heading`` field AST from a DSL string.

    Returns the heading AST as a JSON-compatible dict, or ``None`` if the DSL
    contains no ``heading:`` clause or fails to parse.
    """
    if not dsl_text or not dsl_text.strip():
        return None
    result = parse_dsl(dsl_text)
    if not result.ok:
        return None
    heading_expr = result.text_fields.get("heading")
    if heading_expr is None:
        return None
    if isinstance(heading_expr, ProximityOp):
        # Proximity is not representable in the legacy heading AST format
        return None
    from agent.query_filters import filter_expr_to_json  # noqa: F811
    return filter_expr_to_json(heading_expr)


# ---------------------------------------------------------------------------
# DSL-to-JSON helpers (for API response)
# ---------------------------------------------------------------------------

def dsl_result_to_json(result: DslParseResult) -> dict[str, Any]:
    """Convert a DslParseResult to a JSON-serializable dict.

    Used by the ``POST /api/links/rules/validate-dsl`` endpoint response.
    """
    from agent.query_filters import filter_expr_to_json, meta_filter_to_json

    text_ast: dict[str, Any] = {}
    for fname, expr in result.text_fields.items():
        if isinstance(expr, ProximityOp):
            text_ast[fname] = {
                "type": "proximity",
                "left": filter_expr_to_json(expr.left),
                "right": filter_expr_to_json(expr.right),
                "kind": expr.kind,
                "distance": expr.distance,
            }
        else:
            text_ast[fname] = filter_expr_to_json(expr)

    meta_ast: dict[str, Any] = {}
    for fname, meta in result.meta_fields.items():
        meta_ast[fname] = meta_filter_to_json(meta)

    return {
        "ast": {**text_ast, **meta_ast},
        "normalized_text": result.normalized_text,
        "errors": [
            {"message": e.message, "position": e.position, "field": e.field}
            for e in result.errors
        ],
        "query_cost": result.query_cost,
    }
