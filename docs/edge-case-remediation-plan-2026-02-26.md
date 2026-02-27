# Edge Case Remediation Plan (P0/P1/P2)
Date: 2026-02-26  
Depends on: `docs/edge-case-root-cause-analysis-2026-02-26.md`
Execution board: `docs/edge-case-execution-board-2026-02-26.md`

## Goal
Turn edge-case output from mixed/noisy telemetry into a reliable parser-integrity gate for ontology linking quality.

## Scope Boundaries
- In scope: edge-case detector logic, parser integrity checks, definition/clause extraction quality, dashboard grouping, validation harness.
- Out of scope for this phase: ontology taxonomy redesign, UI visual redesign, embedding/reranking strategy changes.

## Success Metrics
- Parser-integrity signal precision improves (fewer baseline-enrichment false alarms mixed into parser defects).
- `missing_sections` and `zero_definitions` docs are reduced with measurable parser recovery.
- Defined-term links preserve complete definition spans (no 2,000-char clipping artifacts).
- Clause-path anomalies (`_dup` bursts, depth resets, root-label explosions) are reduced and regression-tested.

## Workstreams
- WS1: Edge-case framework calibration (`dashboard/api/server.py` edge-case queries and aggregation)
- WS2: Section/clause parser integrity (section parse fallback + clause path canonicalization)
- WS3: Definition extraction quality (length cap, span bounding, signature-page exclusion)
- WS4: Validation + rollout controls (fixtures, metrics, regression thresholds)

## P0 Tickets (Immediate)
### EC-P0-01: Split Baseline Coverage vs Parser Integrity Views
- Problem: baseline metadata gaps dominate edge-case noise.
- Root cause: enrichment categories and parser-defect categories are mixed in one default view.
- Changes:
  - Add category grouping metadata: `baseline_enrichment`, `parser_integrity`, `outlier_monitoring`.
  - Default edge-case page/API filter to `parser_integrity`; keep a toggle for all categories.
  - Preserve current totals, but show grouped counters.
- Acceptance:
  - Parser-integrity view excludes `orphan_template`, `missing_facility_size`, `missing_borrower`, `missing_closing_date`.
  - API supports group filter and remains backward-compatible.

### EC-P0-02: Reactivate Dormant Detectors with Corrected Logic
- Problem: 12 configured categories have zero signal; some are dead due to logic drift.
- Root cause: stale thresholds and query assumptions.
- Changes:
  - Fix `definition_malformed_term` newline/escaping detector behavior.
  - Update `section_numbering_gap` for dot-style numbering and mixed formats.
  - Recalibrate or retire `deep_nesting_outlier` (`tree_level > 4` currently impossible in corpus).
  - Add explicit detector status (`active`, `monitor-only`, `retired`) to config.
- Acceptance:
  - At least these detectors become meaningful (`active` with expected non-zero or intentionally `monitor-only` with rationale).
  - No detector silently dead without status annotation.

### EC-P0-03: Guardrail Gate for Clause Collision Families
- Problem: `_dup` cascades and depth resets degrade clause-level linking quality.
- Root cause: clause id collision handling allows unstable canonical paths.
- Changes:
  - Add hard regression gate metrics: dup ratio, root-label repeat count, depth reset frequency.
  - Block parser changes from merging if these regress beyond threshold.
  - Promote these categories to top of parser-integrity dashboard.
- Acceptance:
  - CI or local validation command emits pass/fail for collision metrics.
  - Edge-case dashboard clearly surfaces these as critical parser anomalies.

## P1 Tickets (Parser/Extractor Quality)
### EC-P1-01: Section Parse Recovery for Missing-Sections Cluster
- Problem: `missing_sections` docs collapse downstream definitions and linking.
- Root cause: section parser entry failures on non-standard heading formats.
- Changes:
  - Add fallback heading recognizer for common non-standard formats.
  - Record parser attempt trace per doc (mode, fallback used, failure reason).
  - Re-run targeted corpus subset and compare recovery rate.
- Acceptance:
  - Measurable reduction in `missing_sections` and `zero_definitions`.
  - Recovered docs have stable section inventory and parser trace diagnostics.

### EC-P1-02: Clause Path Canonicalization (Stop `_dup` Cascades)
- Problem: clause identifiers drift (e.g., wrong shallow/deep path labels).
- Root cause: duplicate branch preservation instead of canonical parent-path consolidation.
- Changes:
  - Introduce canonical clause-path reconstruction rules.
  - Keep raw parse nodes for audit, but emit stable canonical path for linking/storage.
  - Validate against known bad examples (including `2.21(a)(i)` vs truncated forms).
- Acceptance:
  - Material drop in `clause_dup_id_burst`, `clause_root_label_repeat_explosion`, `clause_depth_reset_after_deep`.
  - Review/query preview uses canonical clause paths consistently.

### EC-P1-03: Remove Definition Truncation Cap + Preserve Span Integrity
- Problem: long definitions truncated near 1999-2000 chars.
- Root cause: hard extraction cap.
- Changes:
  - Remove/raise hard cap and store full text span.
  - Preserve extraction provenance (start/end offsets).
  - Add size-safe storage/serialization checks.
- Acceptance:
  - `definition_truncated_at_cap` drops to near-zero.
  - Terms like `Consolidated EBITDA` render full definition in preview/review.

### EC-P1-04: Signature-Page Exclusion in Definition Extraction
- Problem: signature text leaks into definition candidates.
- Root cause: extraction scope includes trailing signature blocks.
- Changes:
  - Add signature-page boundary detection and exclusion heuristics.
  - Add blacklist phrase set (`By`, `Name`, `Title`, `Signature Page`) scoped to definition extraction stage.
- Acceptance:
  - `definition_signature_leak` materially reduced.
  - No false suppression of valid definitions in sampled docs.

## P2 Tickets (Calibration and Optimization)
### EC-P2-01: Rebalance `low_definitions` Threshold
- Problem: high prevalence category masks more important defects.
- Root cause: threshold tuned too aggressively for corpus variability.
- Changes:
  - Recompute baseline distribution by document type/cohort.
  - Move to percentile-based thresholding per cohort or parser mode.
- Acceptance:
  - `low_definitions` remains informative, no longer dominating parser-integrity queue.

### EC-P2-02: Add Normalized Duplicate Definition Detector
- Problem: exact duplicate detector is silent, but semantic/normalized duplicates still occur.
- Root cause: detector only checks strict equality.
- Changes:
  - Add normalized-term duplicate rules (case/punctuation/whitespace normalization).
  - Track duplicates within and across likely definition sections.
- Acceptance:
  - New detector produces actionable hits with low false-positive rate.

### EC-P2-03: Demote Pure Outlier Categories to Monitoring
- Problem: outlier-only categories distract from parser fixes.
- Root cause: operational and parser-integrity concerns share one severity channel.
- Changes:
  - Move `extreme_word_count`, `non_cohort_large_doc`, etc. into monitor channel.
  - Keep trend charts but remove from default defect queue.
- Acceptance:
  - Parser defect triage feed focuses on fixable parsing/extraction issues.

## Validation Harness
### Regression Suite
- Gold fixtures for:
  - long definitions (`Consolidated EBITDA`-style)
  - deep clause hierarchies (`6.01(a)(iii)`, `2.21(a)(i)(A)` patterns)
  - signature-heavy docs
  - non-standard section heading docs
- Assertions:
  - full definition span retained
  - canonical clause path stability
  - edge-case categories fire with expected severity/status

### Batch Metrics to Report Each Run
- total flagged docs by group (`baseline_enrichment`, `parser_integrity`, `outlier_monitoring`)
- category hit count deltas
- clause collision metrics (`dup_ratio`, root-repeat, depth reset)
- definition integrity metrics (truncation count, signature leak count)

### Clause Guardrail Command (EC-P0-03)
- Merge gate command:
  - `python3 scripts/edge_case_clause_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_guardrail_baseline.json`
- Parent-link merge gate command:
  - `python3 scripts/edge_case_clause_parent_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json`
- Baseline refresh command (intentional only):
  - `python3 scripts/edge_case_clause_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_guardrail_baseline.json --write-baseline`
  - `python3 scripts/edge_case_clause_parent_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json --write-baseline`

## Recommended Execution Order
1. EC-P0-01 and EC-P0-02 (reduce noise + reactivate detectors)
2. EC-P0-03 (install parser guardrails)
3. EC-P1-03 and EC-P1-04 (definition quality blockers for linking)
4. EC-P1-02 (clause canonicalization)
5. EC-P1-01 (section recovery)
6. P2 calibration tickets

## Rollout Strategy
- Phase A: shadow mode (collect new detector outputs without impacting existing views).
- Phase B: dual reporting (old + new category grouping side-by-side).
- Phase C: switch default to parser-integrity queue and keep legacy toggle.

## Owner Lanes
- Backend parser lane: EC-P1-01, EC-P1-02
- Definition extraction lane: EC-P1-03, EC-P1-04
- Edge-case framework lane: EC-P0-01, EC-P0-02, EC-P2-01, EC-P2-03
- QA/validation lane: EC-P0-03, EC-P2-02, regression harness maintenance
