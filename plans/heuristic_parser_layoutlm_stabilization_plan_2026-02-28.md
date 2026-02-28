# Heuristic Parser Stabilization + LayoutLM Sidecar Plan

Date:
1. 2026-02-28

Status:
1. Draft execution plan (contract-oriented) to eliminate heuristic whack-a-mole and introduce layout-aware ML sidecar infrastructure.

## 0) Goal and Problem Statement
Goal:
1. Improve parser correctness for hard structural edge cases without destabilizing baseline throughput.
2. Replace reactive one-off fixes with a repeatable architecture: deterministic parser + layout-aware sidecar risk validation.

Current problem pattern:
1. New heuristic patches improve one category but regress another (`inline_high_letter_branch`, `structural_child_of_nonstruct_parent`, `_dup` collisions, depth resets).
2. Section extraction and clause-tree assembly are coupled too tightly to text-only signals in pathological formatting scenarios.
3. Root-cause signals are detected after-the-fact, rather than prevented by first-class invariants and policy gates.

## 1) Guiding Principles (Binding)
1. Parser v1-compatible deterministic behavior remains the primary path.
2. Layout model is a sidecar authority for risk/validation, not silent tree overwrite.
3. Any parser behavior change must be tied to:
   1. Root-cause category.
   2. Explicit invariant.
   3. Guardrail detector and no-regression check.
4. Integration scope remains limited to:
   1. `process_document_text(...)`
   2. `scripts/build_corpus_ray_v2.py`
5. All config and thresholds are artifacted per run with precedence:
   1. `CLI > ENV > config > defaults`

## 2) Target Architecture
### 2.1 Deterministic Mainline
1. Existing heuristic parser stays as first-pass structure generator.
2. Add explicit branch-building invariants (parent continuity, duplicate lineage quarantine, deep-reset veto rules).

### 2.2 Layout-Aware Sidecar
1. HTML is rendered under pinned profile to deterministic PDF artifacts.
2. Token+bbox extraction produces layout evidence per section.
3. Layout sidecar model (LayoutLM-family) emits:
   1. `p_structural`
   2. `p_parent_correct`
   3. `layout_disagreement_score`
   4. `abstain_recommendation`
4. Sidecar outputs are policy-constrained:
   1. Can veto risky accepts.
   2. Can escalate to review/abstain.
   3. Cannot silently rewrite full parse tree.

### 2.3 Policy Layer
1. Final section outcome uses deterministic policy on:
   1. heuristic confidence,
   2. sidecar disagreement,
   3. guardrail conditions.
2. Low-confidence/high-disagreement sections route to review queue with provenance.

## 3) Root-Cause Streams (Non-Overlapping Ownership)
### Stream A: Parent-Drop / High-Letter Continuations
1. Problem:
   1. `2.11(x)` promoted to root when true structure is `2.11(a)(x)`.
2. Deterministic fix:
   1. First-introduced enumerator tracking per section.
   2. Parent assignment continuity constraints before root promotion.
3. Sidecar assist:
   1. Validate parent plausibility using layout-aligned context spans.

### Stream B: Section Parse Hard Failures
1. Problem:
   1. `outline_and_regex_sections_zero` still occurs on a residual set.
2. Deterministic fix:
   1. Expand boundary recognizers and rejection explainability.
   2. Add rejection logs for TOC/ghost/plausibility filters.
3. Sidecar assist:
   1. Heading-confidence signal from layout (font/position cues) to flag likely missed section starts.

### Stream C: Duplicate Collision Cascades
1. Problem:
   1. `_dup` branches can still leak structural descendants.
2. Deterministic fix:
   1. Duplicate-lineage quarantine.
   2. Ancestor consistency hard constraints for duplicate ancestry.
3. Sidecar assist:
   1. Confidence veto when structural branch boundaries conflict with visual list hierarchy.

### Stream D: Xref vs Structural Confusion
1. Problem:
   1. Inline citations are still occasionally promoted as structure.
2. Deterministic fix:
   1. Separate xref-context penalties from inline-list penalties.
   2. Remove reward paths that can accidentally boost xref-like nodes.
3. Sidecar assist:
   1. Local layout/lexical disagreement signal for enumerator role classification.

## 4) Anti-Whack-a-Mole Control System
### 4.1 Invariant Contract
1. Each root-cause stream gets invariants with pass/fail checks:
   1. `INV-PARENT-001`: no root promotion for high-letter continuation unless hard-boundary evidence.
   2. `INV-DUP-001`: no structural child under duplicate-lineage non-structural ancestors.
   3. `INV-RESET-001`: deep->root reset requires policy-allowed transition.
   4. `INV-XREF-001`: enumerators inside explicit section-clause references cannot become structural roots.

### 4.2 Fixed Regression Packs
1. Freeze doc_id-disjoint packs by failure family:
   1. parent-loss pack,
   2. duplicate-collision pack,
   3. section-miss pack,
   4. xref confusion pack.
2. Every change must pass all packs before shadow run.

### 4.3 Detector-to-Fix Traceability
1. Every detector metric in dashboards/guardrails is mapped to:
   1. owning stream,
   2. expected directional impact,
   3. blocking thresholds.
2. No merged parser change without updated mapping artifact.

### 4.4 Change Budget
1. One stream-level logic change per wave unless evidence shows no interaction risk.
2. Require A/B deltas per stream before combining patches.

## 5) LayoutLM Infrastructure Plan
### Phase L0: Rendering and Determinism Foundation
1. Adopt pinned render profile:
   1. `config/layout_render_profile_v1.json`
2. Implement validator:
   1. `scripts/validate_layout_render_drift.py`
   2. Spec: `docs/operations/layout_render_drift_validator_spec_2026-02-28.md`
3. Gate:
   1. Layout signals are unusable when drift validator fails.

### Phase L1: Feature Pipeline
1. Build token+bbox extraction artifacts for flagged sections only.
2. Persist sidecar features in dedicated artifacts/tables (shadow-only pre-GL3).
3. Ensure provenance fields include:
   1. renderer version,
   2. profile hash,
   3. page/token hashes.

### Phase L2: Sidecar Model (Validator-Only)
1. Train/evaluate LayoutLM-family classifier for risk outputs (not direct tree emission).
2. Targets:
   1. structural-vs-xref risk,
   2. parent correctness risk,
   3. abstain trigger risk.
3. Thresholds calibrated per class with global safety floors.

### Phase L3: Policy Integration
1. Integrate sidecar into parser policy layer in shadow mode.
2. Enable only:
   1. review escalation,
   2. abstain recommendation,
   3. parent-link veto.
3. Keep deterministic parser output as canonical parse proposal until gate signoff.

## 6) Execution Phases (Broad Timeline)
### Phase 1 (Week 1): Deterministic Guardrail Hardening
1. Ship Stream A + Stream C deterministic invariants.
2. Add invariant checks to existing validator/day-bundle flow.
3. Produce no-regression evidence on fixed packs.

### Phase 2 (Week 2): Section + Xref Deterministic Corrections
1. Ship Stream B + Stream D deterministic changes.
2. Add section rejection reason artifacts and xref penalty separation.
3. Re-run guardrails and compare against frozen baseline.

### Phase 3 (Week 3): Layout Infra Bring-Up
1. Implement render drift validator and batch execution path.
2. Generate layout artifacts for low-confidence slices.
3. Prove deterministic reproducibility before any model training.

### Phase 4 (Week 4): Layout Sidecar Shadow
1. Train sidecar risk model and run in pure shadow.
2. Measure precision/recall of review+abstain recommendations by edge class.
3. Promote only if sidecar improves safety metrics without recall collapse.

## 7) Success Criteria
Parser integrity outcomes:
1. Measurable reduction in:
   1. `inline_high_letter_branch`
   2. `structural_child_of_nonstruct_parent`
   3. `clause_dup_id_burst`
   4. `clause_depth_reset_after_deep`
2. `missing_sections` and related downstream misses remain non-regressive and improve where possible.

Sidecar outcomes:
1. Drift validator pass rate satisfies production threshold on shadow cohort.
2. Sidecar disagreement precision is high enough to justify review/abstain escalation.
3. No unauthorized parser-tree overrides from sidecar path.

Operational outcomes:
1. Every wave has:
   1. config artifact,
   2. run manifest,
   3. invariant report,
   4. blocker register updates.

## 8) New Backlog Epics (Proposed)
1. `LAYOUT-001`: deterministic render profile enforcement.
2. `LAYOUT-002`: render drift validator implementation + CI/day-bundle checks.
3. `LAYOUT-003`: token+bbox extraction and sidecar feature schema.
4. `LAYOUT-004`: LayoutLM-sidecar risk model (validator-only).
5. `LAYOUT-005`: policy integration for review/abstain/veto actions.
6. `PARSER-INV-001`: parent/drop invariant framework.
7. `PARSER-INV-002`: duplicate-lineage quarantine invariants.
8. `PARSER-INV-003`: section rejection explainability artifacts.
9. `PARSER-INV-004`: xref-vs-structural penalty decomposition.

## 9) Explicit Non-Goals (For This Plan)
1. No immediate replacement of heuristic parser with full ML tree generation.
2. No canonical DB overwrite from sidecar predictions before launch gates are satisfied.
3. No broad dependency expansion beyond approved runtime constraints without explicit approval.
