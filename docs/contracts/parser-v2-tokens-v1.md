# Parser V2 Token Contract v1
Date: 2026-02-27  
Status: Draft (M0 publish)

## Objective
Define the canonical lexer output schema for parser_v2. Tokens are the only legal input to the candidate-graph layer.

## Token Record
Required fields:
1. `token_id`: deterministic unique id within section parse run.
2. `raw_label`: raw enumerator label, e.g. `(a)`, `(ii)`, `(A)`, `(1)`.
3. `normalized_label`: normalized inner label.
4. `position_start`: absolute char offset (inclusive).
5. `position_end`: absolute char offset (exclusive).
6. `line_index`: 0-based line number.
7. `column_index`: 0-based column index.
8. `is_line_start`: boolean anchor signal.
9. `indentation_score`: float in `[0.0, 1.0]`.
10. `candidate_types`: array of type interpretations (`alpha`, `roman`, `caps`, `numeric`).
11. `ordinal_by_type`: map type -> positive ordinal.
12. `xref_context_features`: map of lexical xref indicators.
13. `layout_features`: map of layout/normalization indicators.
14. `source_span`: `{char_start, char_end}` for traceability.

## Invariants
1. `position_start < position_end`.
2. `candidate_types` non-empty.
3. Every type in `candidate_types` has an entry in `ordinal_by_type`.
4. `token_id` is unique in a section.
5. Token order is stable by `position_start`, tie-break by type precedence.

## Determinism Rules
1. Same normalized input bytes + same lexer version => byte-identical token stream.
2. Tie-break order is fixed and versioned.
3. Any nondeterministic source must be forbidden (no random ordering).

## Versioning
1. Breaking field changes require `parser-v2-tokens-v2`.
2. Additive fields can remain in v1 with optional status until promoted.
