# Edge Cases Root Cause Analysis
Date: 2026-02-26  
Scope: `/api/edge-cases` framework (38 configured categories across 6 tiers), corpus size 3,298 docs.

## Executive Summary
The current edge-case framework is useful, but it mixes three different signal types:
1. Baseline coverage gaps that are expected from incomplete enrichment (`orphan_template`, `missing_facility_size`).
2. Real parser-quality defects (section misses, clause id collision bursts, definition truncation, signature leakage).
3. Dormant checks that currently produce zero signal due threshold or query logic drift.

Key results:
- Total flagged rows: **10,156**.
- Categories with hits: **26/38**.
- Categories with zero hits: **12/38**.
- Top 3 categories account for most volume:
  - `orphan_template`: 3,298 docs (100.0%)
  - `missing_facility_size`: 2,566 docs (77.8%)
  - `low_definitions`: 2,027 docs (61.5%)

High-severity signal is concentrated in 8 categories (837 rows total), with strongest parser defects in:
- `definition_truncated_at_cap` (329 docs)
- `missing_sections` + `zero_definitions` (194 and 187 docs; heavily overlapping)
- `clause_dup_id_burst` (46 docs)
- `clause_root_label_repeat_explosion` (32 docs)
- `definition_signature_leak` (36 docs)

## Method
- Pulled all pages from `/api/edge-cases?cohort_only=false&page_size=200` (51 pages).
- Analyzed full result set (10,156 rows) with DuckDB-backed corpus cross-checks.
- Validated representative docs using:
  - `/api/edge-cases/{doc_id}/clause-detail`
  - `/api/edge-cases/{doc_id}/definition-detail`

## Distribution Overview
### Tier row counts
- template: 3,484
- metadata: 3,182
- definitions: 2,700
- structural: 498
- document: 155
- clauses: 137

### Category prevalence (docs)
- orphan_template: 3,298 (100.0%)
- missing_facility_size: 2,566 (77.8%)
- low_definitions: 2,027 (61.5%)
- definition_truncated_at_cap: 329 (10.0%)
- missing_closing_date: 312 (9.5%)
- missing_borrower: 302 (9.2%)
- empty_section_headings: 258 (7.8%)
- missing_sections: 194 (5.9%)
- zero_definitions: 187 (5.7%)
- non_cohort_large_doc: 185 (5.6%)
- extreme_word_count: 150 (4.5%)
- single_engine_definitions: 116 (3.5%)
- clause_dup_id_burst: 46 (1.4%)
- low_structural_ratio: 42 (1.3%)
- definition_signature_leak: 36 (1.1%)
- low_section_count: 35 (1.1%)
- clause_root_label_repeat_explosion: 32 (1.0%)
- excessive_section_count: 10 (0.3%)
- clause_depth_reset_after_deep: 8 (0.2%)
- low_clause_density: 7 (0.2%)
- high_definition_count: 5 (0.2%)
- very_short_document: 5 (0.2%)
- extreme_facility: 2 (0.1%)
- zero_clauses: 2 (0.1%)
- non_credit_agreement: 1 (0.0%)
- section_fallback_used: 1 (0.0%)

## Root Cause Clusters
## 1) Baseline enrichment not populated (systemic, not parser-specific)
### Evidence
- `orphan_template` is 100%: every document has blank `template_family`.
- `missing_facility_size`: 2,566 docs.
- `missing_borrower`: 302 docs.
- `missing_closing_date`: 312 docs.

### Root cause
- Upstream enrichment fields are not consistently populated in `documents`, so the framework flags missing metadata at scale.
- This currently dominates the dashboard and suppresses parser-quality signal.

### Impact
- High noise floor in edge-case views.
- False perception that all docs are equally problematic.

## 2) Section parser hard failures (high-impact parser defects)
### Evidence
- `missing_sections`: 194 docs.
- `zero_definitions`: 187 docs, with overlap **187/187** with `missing_sections`.
- In these docs: borrower, closing_date, and facility_size are also mostly absent (192+, depending on field).
- `section_parser_mode` is usually blank in this cluster (not `doc_outline`), indicating no successful section parse path.

### Root cause
- Non-standard heading formats or parser entry failure leaves no sections extracted.
- Once sections are absent, definitions and downstream linking quality collapse.

### Impact
- Complete loss of section/definition-linked workflows for affected docs.

## 3) Clause tree collision and duplication (doc_outline-specific)
### Evidence
- `clause_dup_id_burst`: 46 docs, duplication ratio median ~0.938 (min 0.901, max 0.986).
- `clause_root_label_repeat_explosion`: 32 docs (root labels repeated >=200 in one section).
- `clause_depth_reset_after_deep`: 8 docs, typically `m-z`/`y` root resets after deep nodes.
- These categories are entirely in `section_parser_mode='doc_outline'`.
- Example flagged doc shows section `5.13` with hundreds of `(a)/(b)` roots (`a_dup2`, `a_dup3`, ...).

### Root cause
- Clause id collision handling is preserving massive duplicate branches (`_dup` suffixes) instead of converging canonical paths.
- Resulting tree instability also manifests as deep-to-root reset artifacts.

### Impact
- Wrong clause path labels in UI and stored links.
- Inflated candidate counts and noisy previews for clause-scoped linking.

## 4) Definition extraction completeness and contamination issues
### Evidence
- `definition_truncated_at_cap`: 329 docs.
  - Flagged definitions are clustered at exactly 1999-2000 chars (hard cap signature).
  - Common affected terms include `consolidated ebitda`, `cash equivalents`, `defaulting lender`.
- `single_engine_definitions`: 116 docs.
  - Engine distribution is entirely `colon`.
- `definition_signature_leak`: 36 docs.
  - Flagged terms include `Signature Page`, `By`, `Name`, `Title`, `Authorized Signatory`.

### Root cause
- Definition text extraction still uses a hard upper bound, clipping long legal definitions.
- Engine diversity is low on certain docs, suggesting weak quote/parenthetical extraction fallback.
- Signature-page text leaks into definition extraction scope.

### Impact
- Incomplete defined-term links.
- Incorrect term boundaries and noisy rule outcomes when filtering by defined terms.

## 5) Threshold and query drift (dormant or stale checks)
Zero-hit categories (12):
- `section_numbering_gap`
- `low_avg_clause_confidence`
- `orphan_deep_clause`
- `inconsistent_sibling_depth`
- `deep_nesting_outlier`
- `rootless_deep_clause`
- `duplicate_definitions`
- `definition_malformed_term`
- `unknown_doc_type`
- `short_text`
- `extreme_text_ratio`
- `uncertain_market_segment`

### Root-cause notes
- `section_numbering_gap` is effectively dead with current section format assumptions (`section_number NOT LIKE '%.%'`), while the corpus is dot-numbered.
- `deep_nesting_outlier` currently checks `tree_level > 4`, but corpus max tree level is 4.
- `definition_malformed_term` appears dead due escaping mismatch in newline regex pattern (query-level behavior differs from intended detector behavior).
- `unknown_doc_type` and `uncertain_market_segment` are dead because upstream classifications are now consistently populated.

## Quality-Risk Prioritization
P0 (immediate, high signal)
1. Separate baseline metadata categories from parser integrity categories in default edge-case views.
2. Fix dormant query logic:
   - `definition_malformed_term` newline regex behavior.
   - `section_numbering_gap` logic for dot-style section numbering.
   - retire or recalibrate `deep_nesting_outlier` threshold.
3. Keep clause collision categories front-and-center (`clause_dup_id_burst`, `clause_root_label_repeat_explosion`, `clause_depth_reset_after_deep`) for parser triage.

P1 (parser quality)
1. Address section parser failures for docs with `missing_sections` and blank parser mode.
2. Reduce `_dup` cascade in clause id generation and enforce canonical parent-path constraints.
3. Remove or raise the 2,000-char definition cap; preserve full definition text spans.
4. Add signature-page exclusion guardrails before definition extraction.

P2 (framework calibration)
1. Re-balance `low_definitions` threshold (current threshold drives 61.5% prevalence and dominates signal).
2. Add near-duplicate definition detection (normalized-term duplicate checks), since exact duplicates are zero but normalized duplicates are common.
3. Reclassify outlier-only categories (`extreme_word_count`, etc.) as monitoring/telemetry rather than parser failure.

## Practical Interpretation for Ontology Linking
- Most harmful errors for linking quality are not the highest-volume categories.
- Highest-volume categories are baseline metadata gaps; highest-linkage-risk categories are:
  - missing sections / zero definitions
  - clause duplication/tree reset anomalies
  - definition truncation and signature leakage
- This suggests operating with two dashboards:
  1. Coverage baseline (metadata/enrichment)
  2. Linking integrity (parser and extraction defects)

