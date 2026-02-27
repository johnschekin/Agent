# Parser V2 Token Contract v1
Date: 2026-02-27  
Status: Active (M2)

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
6. `line_index` and `column_index` are non-negative.
7. `indentation_score` must be in `[0.0, 1.0]`.
8. `source_span.char_start == position_start`.
9. `source_span.char_end == position_end`.
10. `layout_features.line_start_match == is_line_start`.

## Determinism Rules
1. Same normalized input bytes + same lexer version => byte-identical token stream.
2. Tie-break order is fixed and versioned.
3. Any nondeterministic source must be forbidden (no random ordering).

## Versioning
1. Breaking field changes require `parser-v2-tokens-v2`.
2. Additive fields can remain in v1 with optional status until promoted.

## Tie-break and Candidate Ordering
1. Token rows are ordered by `(position_start, position_end, raw_label)`.
2. `candidate_types` are ordered by canonical depth:
3. `alpha`, `roman`, `caps`, `numeric`.
4. Ambiguous labels keep all plausible candidates (for example `(i)` => `alpha` and `roman`).

## Normative Example
Source:
1. `(a) Parent clause.`
2. `(i) Child one.`
3. `subject to clause (i) above.`

Example token (abridged):
```json
{
  "token_id": "tok_00002_19",
  "raw_label": "(i)",
  "normalized_label": "i",
  "position_start": 19,
  "position_end": 22,
  "is_line_start": true,
  "candidate_types": ["alpha", "roman"],
  "ordinal_by_type": {"alpha": 9, "roman": 1},
  "xref_context_features": {
    "xref_keyword_pre": true,
    "xref_keyword_post": true,
    "xref_preposition_pre": false
  }
}
```

## Snapshot Contract
1. The canonical lexer snapshot fixture is:
2. `tests/fixtures/parser_v2/token_snapshot_v1.json`
3. It is enforced by:
4. `tests/test_parser_v2_lexer.py::test_lexer_snapshot_contract_v1`
5. Any intentional lexer-contract change must update both this document and the snapshot fixture in the same change.
