# Clause Parsing Implementation Reference
Date: 2026-02-26
Owner: Ontology Links parser quality track

## 1) Purpose and Scope
This document is a standalone technical reference for the current clause parsing implementation.
It is written so a coding agent can understand architecture, algorithms, heuristics, data contracts,
known defects, and validation workflow without reading other repository files.

It covers:
- Clause enumerator scanning and normalization.
- Clause tree construction and path generation.
- Confidence scoring and structural demotion logic.
- Persistence schema and downstream consumers.
- Guardrail framework and no-rebuild shadow reparse workflow.
- Current known issues and complexity tradeoffs.

## 2) End-to-End Pipeline
High-level flow:
1. Raw HTML is normalized to `normalized_text`.
2. Section boundaries are parsed.
3. For each section, `parse_clauses(section_text, global_offset=section.char_start)` runs.
4. Returned nodes are persisted into `clauses` and `clause_features`.
5. Downstream linking/query/review uses persisted clause rows (`clause_id`, `parent_id`, `span_start`, `span_end`, `clause_text`, `is_structural`, `parse_confidence`).

Where this happens:
- `src/agent/document_processor.py` in `process_document_text(...)`.
- `scripts/build_corpus_index.py` and `scripts/build_corpus_ray_v2.py` consume `process_document_text(...)` outputs.

Cross-reference resolver path:
- `DocOutline.resolve_xref(...)` uses `parse_clauses(...)` + `resolve_path(...)` to convert `Section X.Y(a)(i)` into exact character span.

## 3) Module Architecture
Primary modules:
- `src/agent/enumerator.py`
- `src/agent/clause_parser.py`

Design split:
- `enumerator.py`: pattern scanning, ordinal conversion, anchoring, indentation measurement.
- `clause_parser.py`: ambiguity resolution, tree construction, span computation, xref filtering, structural confidence scoring.

## 4) Data Contracts

### 4.1 In-memory node contract
Final output node type: `ClauseNode`.
Fields:
- `id`: dot-path ID like `a`, `a.i`, `a.i.A`, `a.i.A.1`.
- `label`: raw enumerator label like `(a)`, `(iv)`, `(A)`, `(1)`.
- `depth`: parser-assigned depth (1 alpha, 2 roman, 3 caps, 4 numeric).
- `level_type`: `alpha|roman|caps|numeric|root`.
- `span_start`, `span_end`: global char offsets in full normalized text.
- `header_text`: short first fragment after label (<=80 chars, sentence/semicolon truncated).
- `parent_id`, `children_ids`: tree links.
- `anchor_ok`, `run_length_ok`, `gap_ok`, `indentation_score`, `xref_suspected`.
- `is_structural_candidate`: main structural/not-structural switch.
- `parse_confidence`: 0.0 to 1.0.
- `demotion_reason`: reason code if demoted.

### 4.2 Persisted clause table contract
`clauses` table columns used by parser output:
- `doc_id`, `section_number`, `clause_id`
- `label`, `depth`, `level_type`
- `span_start`, `span_end`, `header_text`, `clause_text`
- `parent_id`, `is_structural`, `parse_confidence`

Primary key:
- `(doc_id, section_number, clause_id)`

Important:
- `clause_id` is section-scoped path, not globally unique by itself.
- `span_start/span_end` are global to full document text.
- `clause_text` is slice `[span_start:span_end]` of normalized text when bounds are valid.

## 5) Enumerator Layer (`enumerator.py`)

### 5.1 Constants
- `CANONICAL_DEPTH`:
  - alpha: 1
  - roman: 2
  - caps: 3
  - numeric: 4
- `ROMAN_VALUES`: roman numeral map up to xxv (25).

### 5.2 Regex scanners
Parenthesized forms:
- Alpha: `(a)` to `(z)` and doubled letters `(aa)` style.
- Roman: `(i)` style roman patterns.
- Caps: `(A)` style.
- Numeric: `(1)` style.

Period-delimited forms (line-start anchored only):
- `a.`, `iv.`, `A.`, `1.`

### 5.3 Helper functions and behavior
- `roman_to_int(s)`, `int_to_roman(n)`: roman normalization.
- `_alpha_ordinal`, `_caps_ordinal`, `_numeric_ordinal`: label->ordinal converters.
- `ordinal_for(level_type, label)`: unified ordinal converter.
- `next_ordinal_label(level_type, current_ordinal)`: next-sequence label generator.
- `compute_line_starts(text)`: precomputes line starts for O(log n) anchor checks.
- `is_at_line_start(position, line_starts, text)`: first non-whitespace on line detection.
- `check_anchor(position, text, line_starts, lookback=20)`:
  - anchored if at start-of-text or line start.
  - also anchored if near hard boundary (`;`, `:`, or sentence-end plus newline/space).
- `scan_enumerators(text, line_starts=None, deduplicate_alpha_roman=True)`:
  - scans all regex families and returns sorted `EnumeratorMatch` list.
  - optional alpha/roman dedup at same position.
- `disambiguate_i(matches, lookahead_chars=5000)`:
  - legacy utility for `(i)` disambiguation; not the primary path used by `parse_clauses`.
- `compute_indentation(position, text, line_starts)`:
  - indentation score normalized to `[0.0, 1.0]` using 20-space saturation.

## 6) Clause Parser Layer (`clause_parser.py`)

### 6.1 Public API
- `parse_clauses(text, global_offset=0) -> list[ClauseNode]`
- `resolve_path(nodes, path_labels) -> ClauseNode|None`
- `parse_clause_tree(text, global_offset=0) -> ClauseTree`
- `ClauseTree` wrapper helpers:
  - `.roots`
  - `.node_by_id(id)`
  - `.children_of(parent_id)`
  - `.resolve(path)`
  - `.as_records()`

### 6.2 Internal constants and thresholds
Confidence weights:
- Anchor: `0.30`
- Run-length: `0.30`
- Gap check: `0.20`
- Not-xref: `0.15`
- Indentation: `0.05`

Structural threshold:
- `is_structural_candidate = (parse_confidence >= 0.5)`

Header extraction:
- max 80 chars, truncates on first semicolon or sentence period-space.

High-letter continuation handling:
- Continuation letters set: `{x, y, z}`
- Connector lookback regex includes `and`, `or`, comma, semicolon, `provided that`, `subject to`.

### 6.3 Full function inventory and behavior

#### Xref / inline detection helpers
- `_is_xref(text, pos, match_end)`:
  - lookback context for `Section 2.14(` style references.
  - inline citation heuristics when multiple citation-like tokens plus conjunction tail.
  - lookahead checks for `of this Section`, `above`, `hereof`, `hereunder`, etc.
- `_detect_inline_enums(matches, text, line_starts)`:
  - groups matches by line and type.
  - marks same-line list-style sequences as inline-xref candidates.
- `_classify_ambiguous(label_inner, depth, last_sibling_at_level)`:
  - 4-rule alpha/roman resolution cascade for ambiguous single-letter labels.

#### Tree building helpers
- `_extract_header(text, start)`
- `_is_ghost_clause(body_text)`
- `_build_id(parent_id, label_key)`
- `_label_key(match)`
- `_find_active_root_alpha(stack, node_map)`
- `_find_primary_root_alpha(stack, node_map)`
  - currently present but not used by active tree logic.
- `_count_root_alpha_seen(node_map, before_global_pos)`
- `_find_primary_root_alpha_seen(node_map, before_global_pos)`
- `_looks_like_inline_high_letter_continuation(text, pos)`

#### Core algorithmic functions
- `_build_tree(enumerators, text, global_offset, line_starts, inline_xref_positions)`
  - Processes ordered enumerators.
  - Resolves alpha/roman conflicts at identical positions.
  - Assigns initial depth from `CANONICAL_DEPTH`.
  - Applies x/y/z continuation repair heuristics to avoid false root resets.
  - Maintains stack-based parent assignment.
  - Generates duplicate IDs with `_dupN` suffix when collisions occur.
  - Stores mutable nodes for post-pass span and confidence steps.

- `_compute_spans(nodes, text_len, global_offset)`
  - For siblings, span_end is next sibling’s span_start.
  - Last sibling inherits parent span_end or document end.

- `_compute_confidence(nodes, text, global_offset)`
  - Computes structural confidence and demotion reasons.
  - Special anomaly demotions:
    - `duplicate_id_collision`
    - `ordinal_repeat_anomaly`
    - `depth_reset_anomaly`
  - Hard singleton demotion when run-length fails.
  - Ghost-body demotion after confidence pass.
  - Ancestor chain guardrail demotes children under non-structural/noisy ancestors.

### 6.4 Main parse execution order (`parse_clauses`)
1. Return `[]` if input empty.
2. Compute line starts.
3. Scan enumerators with `deduplicate_alpha_roman=False`.
4. Detect inline enumerations.
5. Build mutable tree.
6. Compute spans.
7. Compute confidence/demotion.
8. Convert mutable rows to immutable `ClauseNode` records.

## 7) Confidence and Demotion Semantics

### 7.1 Confidence signals
Signal booleans:
- anchor valid
- sibling run-length valid
- ordinal gap valid
- not xref
- indentation score

### 7.2 Demotion reasons currently emitted
- `singleton`
- `ghost_body`
- `not_anchored`
- `ordinal_gap`
- `cross_reference`
- `duplicate_id_collision`
- `ordinal_repeat_anomaly`
- `depth_reset_anomaly`
- `non_structural_ancestor`

Notes:
- Duplicate IDs are kept for audit visibility but demoted from structural graph.
- Ancestor guardrail can demote structurally-scored children to prevent propagation from known noisy parent branches.

## 8) x/y Parent-Loss Fix Logic (Current)
The parser now has two high-letter continuation repair paths:

Path A (active subtree context):
- Trigger when parsing alpha `x/y/z` at depth 1 while stack top depth >= 2.
- If ordinal jump from primary root alpha is large, force nesting under primary root alpha.

Path B (inline continuation context):
- Trigger when alpha `x/y/z` appears with connector-like lookback text and low root-alpha diversity.
- Uses earliest seen root alpha as parent anchor when sequence shape suggests inline continuation.

Intended effect:
- Convert false root `x` or `y` into `a.x` / `a.y` where legal text indicates continuation under `(a)`.

Non-goal:
- Do not break genuinely long root runs `a..y` where `x/y` are legitimate root siblings.

## 9) Persist/Consumer Dependencies

### 9.1 Persisted outputs used by linking
Downstream linking and review rely on:
- `clause_id` path for row labeling and dedupe keys.
- `clause_text` for clause-scoped filter matching and preview highlights.
- `span_start/span_end` for precise reader jump/highlight.
- `parent_id` and `is_structural` for hierarchy and noise suppression.

### 9.2 Cross-reference resolver dependency
`DocOutline.resolve_xref(...)` parses target section with `parse_clauses` and resolves clause path via `resolve_path`.
If parser path is wrong, xref resolution spans will be wrong.

## 10) Guardrails and QA Framework

### 10.1 Corpus collision guardrail
Script: `scripts/edge_case_clause_guardrail.py`

Monitored metrics:
- `clause_dup_id_burst` (high `_dup` structural ratio)
- `clause_root_label_repeat_explosion` (root label repeated at pathological counts)
- `clause_depth_reset_after_deep` (deep-to-root reset anomalies)

### 10.2 Parent-loss guardrail
Script: `scripts/edge_case_clause_parent_guardrail.py`

Monitored metrics:
- docs/sections with suspicious pattern:
  - depth-1 `a` exists
  - depth-1 `x/y` exists
  - `(a)` text references `(x)` or `(y)`
- continuation-like high-letter row ratio.

### 10.3 Shadow reparse (no rebuild)
Script: `scripts/clause_shadow_reparse_diff.py`

Purpose:
- Reparse selected sections in-memory with current parser.
- Compare to persisted rows without rebuilding corpus index.

Outputs:
- persisted metrics
- shadow metrics
- deltas
- fixed/regressed section samples
- structural key add/remove samples

Regression mode:
- `--fail-on-regression`
- optional `--max-structural-delta-ratio` ceiling

## 11) Current Known Issues (Active)

1. Residual root high-letter artifacts still appear on some sections.
- Symptom: section identifiers like `2.11(x)` or `6.11(y)` when parent context suggests missing `(a)`.
- Complication: some `x/y` roots are legitimate; this is an ambiguous classification task.

2. Mixed false-positive and true-positive root x/y population.
- A strict “always nest x/y” rule breaks legitimate root sequences.
- Current implementation uses heuristics; edge corpus still has unresolved cases.

3. Duplicate branch cascades remain in difficult sections.
- `_dup` retention is intentional for auditability but can inflate downstream candidate volume.

4. Deep reset and ordinal spike anomalies still occur on a minority of docs.
- They are tracked by guardrails and edge-case categories.

5. Parser quality and consumer UX are tightly coupled.
- Wrong pathing directly affects query previews, clause-level highlights, and link storage keys.

## 12) Why This Task Is Intrinsically Complex

1. Label ambiguity is structural, not incidental.
- `(i)` and `(v)` are both alpha and roman candidates depending on context.

2. Legal drafting mixes structural clauses with inline references.
- Same label token can mean clause definition or citation.

3. Documents vary by style and formatting.
- Parenthesized and period-delimited forms coexist.
- Whitespace and line-break patterns are inconsistent.

4. Local decisions have global tree effects.
- One wrong parent assignment can invalidate descendant paths, spans, and review highlights.

5. There is no perfect static rule for high-letter branches.
- Distinguishing true root `(x)` vs continuation `(x)` requires weak context signals.

6. Quality goals are multi-objective.
- Minimize false positives (wrong structural clauses).
- Minimize false negatives (missing valid clauses).
- Preserve stable IDs for downstream linking and dedupe.

## 13) Algorithmic Complexity

For section text length `L` and enumerator match count `M`:
- Enumerator scan: approximately O(L) regex scans over fixed pattern set.
- Build tree: O(M) plus duplicate-ID collision checks (amortized near O(1) map lookups).
- Span computation: O(M log M) worst-case due sibling sorting per parent groups.
- Confidence pass: O(M) plus sibling grouping.

Observed practical bottlenecks are mostly semantic ambiguity, not raw runtime.

## 14) Operational Runbook for Parser Work

Recommended minimal validation set after parser changes:
1. Unit and parser tests:
- `pytest -q tests/test_clause_parser.py -p no:cacheprovider`
2. Edge-case guardrails:
- `python3 scripts/edge_case_clause_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_guardrail_baseline.json`
- `python3 scripts/edge_case_clause_parent_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json`
3. No-rebuild shadow verification:
- `python3 scripts/clause_shadow_reparse_diff.py --db corpus_index/corpus.duckdb --mode parent-loss --json`
4. Manual spot check:
- sample sections with `x/y` roots and confirm whether parent context is preserved.

## 15) Quick Reference: Core Functions and Responsibilities

Enumerator layer:
- `scan_enumerators`: token discovery.
- `check_anchor`: structural validity prior.
- `compute_indentation`: nesting prior.

Clause parser layer:
- `parse_clauses`: orchestration.
- `_build_tree`: hierarchy and path assignment.
- `_compute_spans`: text span boundaries.
- `_compute_confidence`: structural filtering.
- `resolve_path`: explicit path resolution for xref workflows.

Guardrail layer:
- `edge_case_clause_guardrail.py`: collision/reset regression lock.
- `edge_case_clause_parent_guardrail.py`: x/y parent-loss regression lock.
- `clause_shadow_reparse_diff.py`: no-rebuild persisted-vs-shadow diff.

## 16) Bottom Line for New Coding Agents
If you change clause parsing logic, you are changing:
- path IDs used in linking and dedupe,
- preview spans and highlight behavior,
- edge-case incidence and guardrail outputs,
- xref resolution fidelity.

Treat every change as a schema-and-behavior change, not just a parser tweak.
