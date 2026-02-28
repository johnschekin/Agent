# Parsing Improvement Backlog (2026-02-28)

## Purpose
Capture parser improvements that raise structural accuracy and label quality for the hybrid parser/ML program.

## Scope
- `process_document_text` and downstream parser paths.
- No silent behavior changes without explicit artifacted config and validation evidence.

## Backlog

### PARSE-001 (P0) - Defined-Terms Decomposition Mode
Status: `open`

Problem:
- `Defined Terms` sections (for example `Section 1.01`) are extremely long and contain dense inline parentheticals/cross-references.
- Parsing the whole section as one clause-tree unit mixes lexical definition content with structural signals and causes noisy labels.

Required approach:
1. Detect defined-terms sections and switch parser to `defined_terms_mode`.
2. Split the section into one parsing unit per defined term entry.
3. Parse each term entry independently for local structure only.
4. Persist each term-unit with provenance fields that preserve section context.

Required persistence/provenance fields:
- `doc_id`
- `section_number`
- `term`
- `term_span_start`
- `term_span_end`
- `term_text_sha256`
- `source_snapshot_id`

Acceptance criteria:
1. Parser no longer attempts one monolithic clause tree over entire defined-terms sections.
2. Each extracted term appears as an independent parse unit with stable IDs and provenance.
3. Inline references inside term text are not promoted to structural roots unless structurally valid within that term unit.
4. Regression evidence includes before/after metrics for false structural-node rate on defined-terms sections.
5. Hybrid training export can include accepted term-level units and exclude contaminated or review-only units.

### PARSE-002 (P1) - Section Boundary Contamination Guard
Status: `open`

Problem:
- Some section payloads include cross-section or cross-document spillover, causing invalid adjudication/training rows.

Acceptance criteria:
1. Add detector for boundary contamination (header jumps, instrument drift, extreme span anomalies).
2. Auto-quarantine contaminated rows from accepted structural export.
3. Emit artifacted contamination report per run with row IDs and reason codes.

