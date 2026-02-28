# Hybrid Clause Parsing + ML Edge-Case Program
Date: 2026-02-27
Owner: Parsing Program
Status: Execution-ready
Audience: Any coding agent with no prior conversation context

## 1) Executive Context
This repository currently has two parser paths:
1. `parser_v1` in `src/agent/clause_parser.py` (active in production parsing paths).
2. `parser_v2` in `src/agent/parser_v2/` (shadow and experimentation scaffolding, not production-primary).

Recent findings:
1. `parser_v2` readiness reports show extremely low accepted-rate in current form.
2. Threshold tuning mostly moves rows between `abstain` and `review`, not into reliable `accepted`.
3. Core pipeline still consumes `parser_v1` via `doc_parser.py`, `document_processor.py`, and corpus build scripts.

Decision for this program:
1. Keep `parser_v1` as production baseline now.
2. Build ML only for problematic edge-case decisions.
3. Integrate ML through `parser_v2` contracts and solver interface.
4. Promote ML lane only after hard quality gates pass.

## 2) Ground Truth of Current Codebase
Primary parser in use:
1. `src/agent/clause_parser.py`

Parser v2 modules available:
1. `src/agent/parser_v2/normalization.py`
2. `src/agent/parser_v2/lexer.py`
3. `src/agent/parser_v2/graph_builder.py`
4. `src/agent/parser_v2/graph_edges.py`
5. `src/agent/parser_v2/solver.py`
6. `src/agent/parser_v2/adapter.py`
7. `src/agent/parser_v2/dual_run.py`
8. `src/agent/parser_v2/compare_v1.py`
9. `src/agent/parser_v2/solution_types.py`

Fixture and adjudication assets:
1. `data/fixtures/gold/v1/fixtures.jsonl`
2. `data/fixtures/gold/v1/packs/v1-seed-1000-candidate/fixtures.jsonl`
3. `data/fixtures/gold/v1/adjudication/p0_adjudication_queue_200.jsonl`
4. `data/fixtures/gold/v1/adjudication/p0_adjudication_queue_200_train40.jsonl`
5. `data/fixtures/gold/v1/reason_codes.v1.json`

Quality scripts:
1. `scripts/replay_gold_fixtures.py`
2. `scripts/parser_v2_dual_run.py`
3. `scripts/edge_case_clause_guardrail.py`
4. `scripts/edge_case_clause_parent_guardrail.py`
5. `scripts/validate_gold_fixtures.py`
6. `scripts/build_adjudication_queue.py`
7. `scripts/build_corpus_ray_v2.py`

## 3) Program Goals and Non-Goals
Goals:
1. Improve edge-case parsing quality materially without destabilizing baseline parsing.
2. Replace coupled heuristics in high-risk classes with data-driven scoring.
3. Make `abstain` explicit and calibrated instead of accidental demotion.
4. Build manually adjudicated labels suitable for both parser QA and ML training.
5. Keep linking pipeline backward-compatible during migration.

Non-goals:
1. No full parser rewrite before evidence supports cutover.
2. No ontology taxonomy redesign in this program.
3. No forced removal of `parser_v1` in initial phases.
4. No requirement to rebuild full corpus for every code change.

## 4) Hard Constraints (Must Follow)
1. Do not auto-decide labels for manual adjudication rows.
2. Do not mass-generate rationale text from templates and claim it is manual adjudication.
3. Every manual label must include concrete witness text and explicit structural reasoning.
4. All decisions must be reproducible from fixture IDs and source snapshot IDs.
5. Any production-facing change must be behind a feature flag with rollback path.
6. No destructive git operations (`reset --hard`, forced checkout) unless explicitly requested.

## 5) End-State Architecture
Deterministic layers retained:
1. Text normalization and offset mapping.
2. Enumerator tokenization.
3. Hard structural constraints and invariants.

ML layers introduced:
1. Candidate interpretation scoring for ambiguous token type decisions.
2. Parent-edge scoring for competing parent assignments.
3. Structural-vs-xref disambiguation scoring.
4. Continuation-vs-root high-letter scoring.

Global solve and status:
1. Solver selects best valid tree under hard constraints.
2. Margin and conflict policy emits `accepted`, `review`, or `abstain`.
3. Adapter emits backward-compatible clause payload plus status fields.

## 6) Edge-Case Classes in Scope for ML v1
1. `ambiguous_alpha_roman`
2. `high_letter_continuation`
3. `xref_vs_structural`
4. `nonstruct_parent_chain`

Deferred to later v2 scope:
1. Deep OCR corruption handling.
2. Complex definition-boundary semantic segmentation.
3. Full document-level sequence labeling.

## 7) Manual Labeling Program (Required, Human-Reasoned)
### 7.1 Labeling policy
For each queue row, adjudicator must provide:
1. Witness token(s) and exact snippet(s).
2. Hypothesis A (structural interpretation).
3. Hypothesis B (citation/continuation/conflict interpretation).
4. Why A fails or survives.
5. Why B fails or survives.
6. Final decision.
7. Confidence statement.

Allowed final decisions:
1. `accepted`
2. `review`
3. `abstain`

### 7.2 Required rationale format per row
Each row must contain these fields:
1. `row_id`
2. `fixture_id`
3. `doc_id`
4. `section_number`
5. `witness_snippets`
6. `candidate_interpretations`
7. `decision`
8. `decision_rationale`
9. `confidence_level`
10. `adjudicator_id`
11. `adjudicated_at`

### 7.3 Batch protocol
1. Work in batches of 20 rows.
2. Produce rationale in plain English for all 20.
3. Review and approve batch before write-back.
4. Only then update queue records and fixture adjudication metadata.
5. Repeat for next 20.

### 7.4 Escalation protocol
Escalate to project owner only if:
1. Two interpretations are equally plausible after full context inspection.
2. Source text appears truncated or corrupted beyond deterministic adjudication.
3. Policy choice is required, not technical uncertainty.

### 7.5 Label quality checks
1. Re-adjudicate a random 10% sample after 24h.
2. Measure self-consistency rate.
3. Target consistency >= 95% on non-escalated rows.
4. Any drift triggers taxonomy clarification before more labeling.

## 8) Data Schema for Training Set
Create `data/fixtures/gold/v1/training/edgecase_labels_v1.jsonl` with one record per adjudicated target token/node candidate.

Record fields:
1. `record_id`
2. `fixture_id`
3. `queue_item_id`
4. `doc_id`
5. `section_number`
6. `token_id`
7. `token_label`
8. `token_span_start`
9. `token_span_end`
10. `candidate_type`
11. `candidate_parent_id`
12. `label_is_structural` (0 or 1)
13. `label_is_xref` (0 or 1)
14. `label_selected_parent` (string or null)
15. `label_section_status` (`accepted|review|abstain`)
16. `label_primary_reason`
17. `adjudication_rationale`
18. `adjudicator_id`
19. `adjudicated_at`
20. `source_snapshot_id`

Split manifest:
1. Keep doc-level split map in `data/fixtures/gold/v1/splits.v1.manifest.json`.
2. Never allow same `doc_id` in both train and eval slices.

## 9) ML Model Plan
### 9.1 Baseline model family
Use a staged approach:
1. Stage A: tabular classifier/ranker over engineered features.
2. Stage B: lightweight text encoder for ambiguous cases only.

### 9.2 Features (v1)
1. Token type candidates and ordinals.
2. Relative position and line anchor features.
3. Indentation and layout signals.
4. Local lexical windows around token.
5. Xref lexical trigger features.
6. Parent-edge compatibility features.
7. Sibling continuity features.
8. Span and chain consistency features.

### 9.3 Targets
1. Token interpretation target (`alpha` vs `roman` etc).
2. Parent-edge ranking target.
3. Structural vs xref target.
4. Section-level status target (`accepted|review|abstain`).

### 9.4 Calibration
1. Calibrate margins on validation set.
2. Tune category-specific thresholds.
3. Persist threshold profile in versioned JSON under `artifacts/`.

## 10) Integration Plan with parser_v2
### 10.1 Keep deterministic shell
1. Keep `parser_v2` lexer and candidate graph deterministic.
2. Keep hard constraints deterministic in solver.

### 10.2 Add ML scoring interface
Add new module:
1. `src/agent/parser_v2/ml_scoring.py`

Required interface:
1. `score_token_candidates(...) -> dict[token_id, list[candidate_score]]`
2. `score_parent_edges(...) -> dict[edge_id, score]`
3. `score_structural_vs_xref(...) -> dict[token_id, score]`

### 10.3 Solver hook
Modify `src/agent/parser_v2/solver.py`:
1. Inject scorer implementation by dependency inversion.
2. Default scorer remains deterministic fallback.
3. ML scorer enabled by flag.

### 10.4 Feature flags
Add config flags:
1. `PARSER_V2_ENABLE_ML_SCORER`
2. `PARSER_V2_ML_PROFILE`
3. `PARSER_V2_EDGECASE_ONLY`
4. `PARSER_V2_SHADOW_ONLY`

### 10.5 Adapter contract
`src/agent/parser_v2/adapter.py` must continue emitting legacy-compatible fields plus:
1. `parse_status`
2. `abstain_reason_codes`
3. `solver_margin`
4. `parser_version`

## 11) Evaluation Protocol (Operator-Grade)
This program uses a fixed evaluation protocol so results are comparable across runs and across agents.

Run modes:
1. `baseline`: parser_v1 only, no ML scorer.
2. `shadow`: parser_v1 plus parser_v2(ML) side-by-side, no production write impact.
3. `assist`: parser_v1 output remains authoritative except for explicitly scoped edge-case interventions.

Mandatory datasets for every evaluation cycle:
1. Canonical fixtures: `data/fixtures/gold/v1/fixtures.jsonl`.
2. Candidate fixtures: `data/fixtures/gold/v1/packs/v1-seed-1000-candidate/fixtures.jsonl`.
3. Hard fixtures: `data/fixtures/gold/v1/packs/v1-seed-hard-2500/fixtures.jsonl` (fixed sample slice if needed).
4. Edge-case audit pack: `data/quality/clause_edge_cases_batch_1.jsonl` and subsequent versioned packs.
5. Human-audited release sample: a fixed versioned set created from manual adjudication logs.

Mandatory commands for one full cycle:
1. `python3 scripts/validate_gold_fixtures.py --fixtures data/fixtures/gold/v1/fixtures.jsonl`
2. `python3 scripts/replay_gold_fixtures.py --fixtures data/fixtures/gold/v1/fixtures.jsonl`
3. `python3 scripts/parser_v2_dual_run.py --fixtures data/fixtures/gold/v1/fixtures.jsonl --sidecar artifacts/parser_v2_dual_run_sidecar.jsonl --report artifacts/parser_v2_dual_run_report.json`
4. `python3 scripts/edge_case_clause_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_guardrail_baseline.json`
5. `python3 scripts/edge_case_clause_parent_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json`

Required output artifacts per run:
1. `artifacts/parser_v2_dual_run_report*.json`
2. `artifacts/parser_v2_dual_run_sidecar*.jsonl`
3. `artifacts/parser_v2_*_readiness_summary.json`
4. `artifacts/parsing_ci_gate_*.json`
5. Human audit summary for that run version.

## 12) Hard Launch Gates (SV-Grade Stop/Go)
Every gate below is hard. Failing any gate blocks promotion.

### 12.1 Gate GL0: Baseline Integrity Gate
Purpose: Ensure parser_v1 baseline is stable before any ML promotion discussion.

Pass criteria:
1. All parser_v1 unit tests pass.
2. Fixture replay gate passes for baseline policy profile.
3. No unapproved parser_v1 logic diffs in `src/agent/clause_parser.py`.

Evidence required:
1. Test log artifact.
2. Replay summary artifact.
3. Git diff summary signed in run report.

Fail action:
1. Freeze ML rollout work.
2. Fix parser_v1 baseline drift first.

### 12.2 Gate GL1: Manual Label Quality Gate
Purpose: Block model training on weak labels.

Pass criteria:
1. Minimum 800 manually adjudicated rows in scope categories.
2. 100% rows have full rationale fields (witness snippet, competing hypotheses, final rationale).
3. Re-audit consistency >= 95% on random 10% sample.
4. Escalation rate <= 15% after first 400 labels.

Evidence required:
1. Versioned adjudication log artifact.
2. Re-audit consistency report.
3. Queue completion and schema validation report.

Fail action:
1. Reject training run.
2. Continue adjudication and policy clarification.

### 12.3 Gate GL2: Offline Model Quality Gate
Purpose: Require measurable benefit before any shadow recommendation.

Pass criteria:
1. In-scope edge-case error reduction >= 35% versus deterministic baseline on holdout.
2. Control-set degradation <= 1.5% absolute.
3. Accepted precision on audited holdout >= 98%.
4. Abstain precision >= 90%.
5. Calibration error (ECE or equivalent) <= 0.08 on decision confidence bins.

Evidence required:
1. Model eval report with confusion matrices by category.
2. Calibration report and threshold profile.
3. Error analysis on top 50 failures.

Fail action:
1. No shadow promotion for that model.
2. Iterate on labels/features/calibration.

### 12.4 Gate GL3: Shadow Stability Gate
Purpose: Prove reliability under realistic traffic without production impact.

Pass criteria:
1. Three consecutive shadow runs meet GL2-level precision and abstain quality.
2. Invariant violations remain zero.
3. Parent guardrail and parser-integrity guardrail are non-regressive.
4. p95 parser_v2 section latency increase <= 25% relative to baseline parse step.

Evidence required:
1. Three run artifacts with signed timestamps.
2. Guardrail deltas and latency report.
3. Sidecar drift comparison report.

Fail action:
1. Reset shadow streak counter to zero.
2. Block assist-mode promotion.

### 12.5 Gate GL4: Operations Readiness Gate
Purpose: Ensure release can be safely operated and reversed.

Pass criteria:
1. Feature flags work in staging and local production-like environment.
2. Rollback drill completed in <= 10 minutes.
3. Monitoring alerts configured for precision proxy drift, abstain-rate spikes, and parser latency.
4. On-call runbook approved.

Evidence required:
1. Rollback drill log.
2. Alert dashboard screenshots or exported configs.
3. Approved operations runbook artifact.

Fail action:
1. No production assist traffic.
2. Complete operational controls first.

### 12.6 Gate GL5: Controlled Assist Launch Gate
Purpose: Move from shadow to limited production safely.

Pass criteria:
1. Assist scope limited to the 4 approved edge-case classes.
2. Traffic ramp plan with checkpoints is defined and approved.
3. Human review queue capacity is proven for projected review load.
4. First canary window (for example 5%) meets all quality thresholds for 48 hours.

Evidence required:
1. Canary report with category-wise outcomes.
2. Review queue throughput report.
3. Incident summary (must be zero Sev1/Sev2 attributable to parser assist).

Fail action:
1. Immediate rollback to parser_v1-only.
2. Postmortem before reattempt.

## 13) Launch Decision Governance
Release decisions are made in a formal gate review meeting with documented sign-off.

Required roles:
1. Parser technical owner.
2. Data/adjudication owner.
3. Operations owner.
4. Product owner for review workflow impact.

Decision states:
1. `GO`: all gate criteria met and evidence attached.
2. `NO-GO`: one or more gate criteria failed.
3. `CONDITIONAL GO`: allowed only for shadow progression, never for production assist.

Decision log requirements:
1. Gate outcomes table with each metric and threshold.
2. Linked evidence artifact paths.
3. Explicit owner acknowledgment and timestamp.
4. Follow-up actions with due dates.

## 14) Detailed Implementation Work Plan (Execution-Ready)
### 14.1 Workstream A: Data and Adjudication
Scope:
1. Build and maintain high-quality manual labels for in-scope edge cases.

Files to create:
1. `docs/operations/manual_adjudication_protocol_v1.md`
2. `scripts/validate_manual_adjudication_log.py`
3. `scripts/export_edgecase_training_set.py`
4. `scripts/split_edgecase_training_set.py`
5. `data/fixtures/gold/v1/training/edgecase_labels_v1.jsonl`

Task sequence:
1. Finalize adjudication template and required fields.
2. Process queue in batches of 20 rows with full rationale.
3. Validate schema and rationale completeness after each batch.
4. Re-audit 10% sample daily and publish consistency report.

Exit criteria:
1. GL1 fully satisfied.

### 14.2 Workstream B: ML Scoring Layer
Scope:
1. Implement model-ready feature extraction and scoring interfaces.

Files to create:
1. `src/agent/parser_v2/ml_features.py`
2. `src/agent/parser_v2/ml_scoring.py`
3. `src/agent/parser_v2/ml_calibration.py`
4. `scripts/train_parser_v2_edgecase_model.py`
5. `scripts/eval_parser_v2_edgecase_model.py`
6. `scripts/calibrate_parser_v2_thresholds.py`

Task sequence:
1. Implement deterministic feature extraction from token and edge candidates.
2. Train baseline model on manual labels only.
3. Calibrate thresholds per category.
4. Persist model artifact and threshold profile with version tags.

Exit criteria:
1. GL2 fully satisfied.

### 14.3 Workstream C: Solver and Adapter Integration
Scope:
1. Integrate ML scorer into parser_v2 without breaking contracts.

Files to update:
1. `src/agent/parser_v2/solver.py`
2. `src/agent/parser_v2/solution_types.py`
3. `src/agent/parser_v2/adapter.py`
4. `src/agent/parser_v2/dual_run.py`
5. `docs/contracts/parser_v2_ml_scorer_v1.md`
6. `docs/contracts/parser_v2_edgecase_labels_v1.md`

Task sequence:
1. Add scorer injection interface and default deterministic fallback.
2. Add score provenance fields to solution outputs.
3. Preserve legacy-compatible output fields in adapter.
4. Extend dual-run reports with ML-vs-deterministic diagnostics.

Exit criteria:
1. GL3 preconditions are met.

### 14.4 Workstream D: Test and CI Hardening
Scope:
1. Add enforceable quality automation for every commit.

Files to create:
1. `.github/workflows/parser-ml-gate.yml`
2. `tests/test_parser_v2_ml_features.py`
3. `tests/test_parser_v2_ml_scoring.py`
4. `tests/test_parser_v2_ml_integration.py`
5. `tests/test_manual_adjudication_protocol.py`

Task sequence:
1. Add schema and replay checks.
2. Add model score determinism tests.
3. Add dual-run smoke test with fixed small fixture pack.
4. Add fail-fast enforcement on gate-critical regressions.

Exit criteria:
1. CI is red on any GL0/GL1/GL2 violation.

### 14.5 Workstream E: Release Operations
Scope:
1. Make rollout and rollback operationally safe.

Files to create:
1. `docs/operations/parser_assist_rollout_runbook_v1.md`
2. `docs/operations/parser_assist_rollback_drill_v1.md`
3. `plans/parser_assist_gate_review_template_v1.md`

Task sequence:
1. Implement feature flags and config docs.
2. Define monitoring and alert thresholds.
3. Execute rollback drills and log timings.
4. Run canary ramp with formal gate sign-off.

Exit criteria:
1. GL4 and GL5 satisfied.

## 15) CI and Automation Requirements
The CI workflow must produce machine-readable gate evidence.

Required CI jobs:
1. `fixtures-validate`: schema and split validation.
2. `parser-v1-replay-smoke`: baseline replay on fixed pack.
3. `parser-v2-dualrun-smoke`: deterministic and ML scorer shadow smoke.
4. `ml-unit-tests`: model feature and scorer tests.
5. `guardrail-smoke`: run guardrail scripts on sample DB artifact.
6. `gate-summary`: aggregate job outputs into one JSON gate summary artifact.

Required CI outputs:
1. `artifacts/parsing_ci_gate_<build>.json`
2. Linked logs for each required metric.
3. Pass/fail decision per gate criterion.

## 16) Risk Register (Expanded)
Risk 1: Label inconsistency creates noisy supervision.
Mitigation:
1. Strict rationale schema.
2. Re-audit sample daily.
3. Block training when consistency threshold missed.

Risk 2: Model looks good on fixtures but fails on live extraction noise.
Mitigation:
1. Include adversarial noise fixtures.
2. Track live shadow deltas by source quality flags.
3. Keep abstain conservative initially.

Risk 3: Assist mode increases review workload beyond staffing.
Mitigation:
1. Workload gate in GL5.
2. Category-specific abstain threshold tuning.
3. Immediate rollback on queue saturation.

Risk 4: Integration drift breaks linking output compatibility.
Mitigation:
1. Adapter contract tests.
2. Compare v1/v2 payload shape and required fields in CI.
3. Block merge on contract mismatches.

Risk 5: Overfitting to one edge-case family.
Mitigation:
1. Balanced label composition by category.
2. Holdout by doc_id.
3. Per-category reporting mandatory in gate reviews.

## 17) Rollback and Incident Response Plan
Rollback triggers:
1. Any gate-critical metric breach during canary.
2. Invariant violation count > 0.
3. Accepted precision in audit sample < 98%.
4. Review queue throughput breach for two consecutive hours.

Rollback procedure:
1. Disable `PARSER_V2_ENABLE_ML_SCORER`.
2. Disable `PARSER_V2_EDGECASE_ONLY`.
3. Confirm parser_v1-only routing.
4. Capture incident artifact bundle and freeze model version.
5. Run post-rollback verification replay.

Incident record must include:
1. Triggering metric and threshold.
2. Time to detect and time to rollback.
3. Affected categories.
4. Corrective action with owner and due date.

## 18) First 2-Week Execution Schedule
Week 1 objectives:
1. Finalize adjudication protocol and validation tooling.
2. Complete first 200 manual labels with full rationale.
3. Implement feature extraction scaffold and unit tests.
4. Produce first label consistency report.

Week 2 objectives:
1. Reach 500 manual labels.
2. Train baseline ML scorer and calibration profile.
3. Integrate scorer under shadow flag in parser_v2.
4. Publish first full dual-run delta report.

Week 2 required outputs:
1. Label dataset v1 candidate.
2. Model eval package.
3. Gate-readiness snapshot against GL0-GL2.

## 19) Deliverables and Evidence Package
Required deliverables:
1. Manual adjudication protocol and completed logs.
2. Versioned labeled training dataset.
3. ML scorer code and calibration profile.
4. Dual-run reports with category deltas.
5. Feature-flagged assist implementation.
6. Rollback drill report and runbook.

Required evidence bundle for launch review:
1. Gate table with pass/fail and raw values.
2. Artifact paths for each metric.
3. Canary/ops report.
4. Final go/no-go memo.

## 20) Definition of Done (Program v1, Launch-Ready)
Program v1 is done only when all conditions below are true:
1. Parser_v1 remains stable and validated as fallback baseline.
2. GL0 through GL5 are all passed with evidence attached.
3. In-scope edge-case quality lift is sustained across consecutive shadow runs.
4. Accepted and abstain precision targets are met in audited samples.
5. Manual adjudication process is fully auditable and repeatable.
6. Rollback can be executed within defined recovery time objective.
7. A new coding agent can execute the program using this plan alone.
