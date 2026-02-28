# Hybrid Parser/ML Program: Ticket-Ready Backlog

Source plan:
- `plans/hybrid_ml_parser_master_schedule_2026-02-27.md`
- `plans/hybrid_ml_parser_day_bundle_validator_spec_2026-02-27.md`

Usage:
- Copy each ticket into Jira/Linear as-is.
- Keep IDs stable for traceability in gate review packets.

Conventions:
1. Priority: `P0`, `P1`, `P2`.
2. Estimate unit: engineering days.
3. Gate mapping: GL0-GL5 from hard launch gates.
4. Status values: `todo`, `in_progress`, `blocked`, `done`.

Execution contract (non-optional for every ticket closure):
1. Deliverables must include machine-readable artifacts, not only memo text.
2. Ticket closure requires:
   1. command log,
   2. evidence artifact paths,
   3. validator pass (`day_validator_report.json.status == "pass"`),
   4. explicit blocker lifecycle updates.
3. If workspace is dirty, canonical-routing artifacts are mandatory and primary manifest pointers must target canonical outputs.
4. EOD red-team analysis must be adversarial-subagent-based when `red_team_status` is `in_review|complete`, with artifact + manifest pointer.

Reconciliation reference:
1. Calendar sequencing is defined in:
   1. `plans/hybrid_ml_parser_day_by_day_checklist_2026-02-27.md`
2. If ticket dependencies conflict with a calendar step, dependency order wins.

## Epic E1: Baseline Integrity and Governance

### Ticket PARSER-001
1. Title: Lock parser_v1 baseline and produce GL0 evidence bundle
2. Priority: P0
3. Owner: Parser Tech Lead
4. Estimate: 1.5 days
5. Dependencies: none
6. Gate mapping: GL0
7. Description:
   1. Run baseline fixture replay and both guardrail scripts.
   2. Publish immutable artifact bundle for baseline.
   3. Confirm no unapproved parser_v1 logic drift.
8. Acceptance criteria:
1. All parser_v1 tests pass.
2. Replay and guardrail artifacts saved under versioned run path.
3. Signed GL0 summary memo exists.
4. Day bundle validator passes against GL0 profile.
5. If `git.is_dirty=true`, canonical routing policy exists and is enforced in primary manifest pointers.
6. Parent-guardrail fail at GL0 is handled as launch-blocking debt entry (owner/ETA), not day-close blocker.
9. Deliverables:
   1. `artifacts/*baseline*`
   2. GL0 memo markdown.
10. Status: todo

### Ticket PARSER-002
1. Title: Implement launch gate decision template and sign-off workflow
2. Priority: P1
3. Owner: Program Owner
4. Estimate: 1 day
5. Dependencies: PARSER-001
6. Gate mapping: GL0-GL5 governance
7. Description:
   1. Create reusable gate review template.
   2. Define mandatory sign-off roles and timestamps.
8. Acceptance criteria:
1. Template includes per-gate pass/fail fields and artifact links.
2. Approval workflow documented in plan.
3. Template includes validator status/exit-code fields and canonical-routing attestations.
9. Deliverables:
1. `plans/parser_assist_gate_review_template_v1.md`
10. Status: todo

### Ticket PARSER-003
1. Title: Implement day-bundle validator and day-profile checks
2. Priority: P0
3. Owner: Data Engineer
4. Estimate: 1.5 days
5. Dependencies: PARSER-001, PARSER-002
6. Gate mapping: GL0-GL5
7. Description:
   1. Implement `scripts/validate_day_bundle.py` with strict exit semantics.
   2. Implement profile-driven checks for day-level required artifacts/fields.
   3. Emit machine-readable pass/fail report with failing-check details.
8. Acceptance criteria:
   1. Validator supports `--run-dir`, `--day-id`, `--profile`, `--strict`, `--json-out`.
   2. Validator exits non-zero on missing/invalid contract artifacts.
   3. Validator verifies canonical routing when workspace is dirty.
   4. Validator enforces adversarial subagent red-team artifact contract when red-team status is `in_review|complete`.
   5. Tests cover at least one pass and one fail scenario per profile family.
9. Deliverables:
   1. `scripts/validate_day_bundle.py`
   2. `tests/test_validate_day_bundle.py`
   3. profile definitions under `config/day_bundle_validator/`
10. Status: todo

## Epic E2: Manual Labeling and Data Quality

### Ticket PARSER-010
1. Title: Finalize manual adjudication protocol v1
2. Priority: P0
3. Owner: Data/Adjudication Lead
4. Estimate: 1 day
5. Dependencies: none
6. Gate mapping: GL1
7. Description:
   1. Define required rationale fields and adjudication policy.
   2. Define escalation criteria for ambiguous rows.
8. Acceptance criteria:
1. Protocol document approved.
2. Schema aligns with adjudication logs and validation script.
3. Protocol defines reviewer authority, abstain/escalation policy, and conflict-resolution rules.
9. Deliverables:
   1. `docs/operations/manual_adjudication_protocol_v1.md`
10. Status: todo

### Ticket PARSER-011
1. Title: Build adjudication log schema validator
2. Priority: P0
3. Owner: Data Engineer
4. Estimate: 1.5 days
5. Dependencies: PARSER-010
6. Gate mapping: GL1
7. Description:
   1. Validate schema completeness and rationale content.
   2. Fail on missing witness snippet or missing comparative reasoning.
8. Acceptance criteria:
1. Validator rejects invalid rows with actionable errors.
2. CI job exists for validator.
3. Error output includes row-level field paths and reason codes.
9. Deliverables:
   1. `scripts/validate_manual_adjudication_log.py`
10. Status: todo

### Ticket PARSER-012
1. Title: Complete first 400 manual adjudications with full rationale
2. Priority: P0
3. Owner: Adjudication Team
4. Estimate: 5 days
5. Dependencies: PARSER-010, PARSER-011
6. Gate mapping: GL1
7. Description:
   1. Process queue in batches of 20.
   2. Maintain full rationale quality for each row.
8. Acceptance criteria:
   1. 400 rows validated.
   2. Escalation reasons documented.
9. Deliverables:
   1. Versioned adjudication log batch set.
10. Status: todo

### Ticket PARSER-013
1. Title: Complete adjudication to GL1 threshold (>=800 rows) and consistency audit
2. Priority: P0
3. Owner: Adjudication Team + QA Reviewer
4. Estimate: 5 days
5. Dependencies: PARSER-012
6. Gate mapping: GL1
7. Description:
   1. Extend labels to at least 800 rows.
   2. Perform 10% re-audit and compute consistency.
8. Acceptance criteria:
   1. >=800 validated rows.
   2. >=150 validated rows in each in-scope edge-case class.
   3. Per-class volume remains within target balance range 150-250.
   4. Re-audit consistency >=95%.
   5. Escalation rate <=15%.
9. Deliverables:
   1. GL1 evidence report.
10. Status: todo

### Ticket PARSER-014
1. Title: Export and split labeled dataset by doc_id
2. Priority: P0
3. Owner: Data Engineer
4. Estimate: 1.5 days
5. Dependencies: PARSER-013
6. Gate mapping: GL1, GL2
7. Description:
   1. Export training data from adjudication logs.
   2. Build train/val/holdout split with doc_id isolation.
8. Acceptance criteria:
   1. Split artifacts reproducible with fixed seed.
   2. Leakage checks pass.
9. Deliverables:
   1. `scripts/export_edgecase_training_set.py`
   2. `scripts/split_edgecase_training_set.py`
10. Status: todo

## Epic E3: ML Scorer and Calibration

### Ticket PARSER-020
1. Title: Implement parser_v2 ML feature extraction module
2. Priority: P0
3. Owner: ML Engineer
4. Estimate: 2.5 days
5. Dependencies: PARSER-011
6. Gate mapping: GL2
7. Description:
   1. Build deterministic feature extraction for token/edge candidates.
   2. Include context and ambiguity signals.
   3. Use fixtures/queue samples for scaffold validation; full labeled export not required to start.
8. Acceptance criteria:
   1. Feature extraction deterministic on same input.
   2. Unit tests for schema and stability pass.
9. Deliverables:
   1. `src/agent/parser_v2/ml_features.py`
   2. `tests/test_parser_v2_ml_features.py`
10. Status: todo

### Ticket PARSER-021
1. Title: Implement ML scoring interface with deterministic fallback
2. Priority: P0
3. Owner: ML Engineer
4. Estimate: 2 days
5. Dependencies: PARSER-020
6. Gate mapping: GL2
7. Description:
   1. Provide score functions for candidate selection and structural/xref discrimination.
   2. Preserve deterministic path when flag disabled.
8. Acceptance criteria:
   1. Parser output unchanged when ML flag is off.
   2. Scorer tests pass.
9. Deliverables:
   1. `src/agent/parser_v2/ml_scoring.py`
   2. `tests/test_parser_v2_ml_scoring.py`
10. Status: todo

### Ticket PARSER-022
1. Title: Train baseline edge-case model (manual labels only)
2. Priority: P0
3. Owner: ML Engineer
4. Estimate: 1.5 days
5. Dependencies: PARSER-014, PARSER-020
6. Gate mapping: GL2
7. Description:
   1. Train first model on curated labeled dataset.
   2. Produce eval package with confusion matrices by category.
8. Acceptance criteria:
   1. Eval artifacts generated and versioned.
   2. Holdout metrics reported against GL2 thresholds.
   3. Stage A training uses only approved model families:
      1. regularized logistic regression,
      2. scikit-learn HistGradientBoosting.
   4. No xgboost/lightgbm encoder dependencies in Stage A artifacts.
9. Deliverables:
   1. `scripts/train_parser_v2_edgecase_model.py`
   2. `scripts/eval_parser_v2_edgecase_model.py`
10. Status: todo

### Ticket PARSER-023
1. Title: Calibrate accepted/review/abstain thresholds
2. Priority: P0
3. Owner: ML Engineer
4. Estimate: 1.5 days
5. Dependencies: PARSER-022
6. Gate mapping: GL2
7. Description:
   1. Calibrate thresholds for precision-first policy.
   2. Emit calibration report and threshold profile.
8. Acceptance criteria:
   1. Calibration metric (ECE or equivalent) <=0.08.
   2. Threshold profile is versioned and reproducible.
   3. Thresholds are calibrated per edge-case class.
   4. Global safety floors are encoded and validated in report:
      1. accepted precision floor >=98%,
      2. abstain precision floor >=90%.
9. Deliverables:
   1. `src/agent/parser_v2/ml_calibration.py`
   2. `scripts/calibrate_parser_v2_thresholds.py`
10. Status: todo

## Epic E4: Solver/Adapter Integration and Dual-Run

### Ticket PARSER-030
1. Title: Integrate scorer injection into parser_v2 solver
2. Priority: P0
3. Owner: Parser Engineer
4. Estimate: 2 days
5. Dependencies: PARSER-021
6. Gate mapping: GL2, GL3
7. Description:
   1. Add dependency-injected scorer interface.
   2. Preserve deterministic fallback behavior.
8. Acceptance criteria:
   1. Solver supports both deterministic and ML scorer.
   2. Integration tests pass.
9. Deliverables:
   1. `src/agent/parser_v2/solver.py`
   2. `tests/test_parser_v2_ml_integration.py`
10. Status: todo

### Ticket PARSER-031
1. Title: Extend adapter contract for parse status and abstain reasons
2. Priority: P0
3. Owner: Parser Engineer
4. Estimate: 1.5 days
5. Dependencies: PARSER-030
6. Gate mapping: GL3
7. Description:
   1. Emit `parse_status`, `abstain_reason_codes`, `solver_margin`, `parser_version`.
   2. Keep legacy-compatible required fields unchanged.
8. Acceptance criteria:
   1. Contract tests validate payload shape compatibility.
   2. UI-consuming APIs remain backward compatible.
9. Deliverables:
   1. `src/agent/parser_v2/adapter.py`
   2. `docs/contracts/parser_v2_ml_scorer_v1.md`
10. Status: todo

### Ticket PARSER-032
1. Title: Produce parser_v2 dual-run diagnostics and sidecar reporting
2. Priority: P0
3. Owner: Parser Engineer
4. Estimate: 1.5 days
5. Dependencies: PARSER-031, PARSER-023
6. Gate mapping: GL3
7. Description:
   1. Run side-by-side parse with deterministic and ML scorer.
   2. Report category-level deltas and abstain impacts.
8. Acceptance criteria:
   1. Sidecar and report artifacts produced per run.
   2. Shadow run comparison summary is machine-readable.
9. Deliverables:
   1. `src/agent/parser_v2/dual_run.py`
   2. `artifacts/parser_v2_dual_run_report*.json`
10. Status: todo

## Epic E5: CI, Guardrails, and Release Operations

### Ticket PARSER-040
1. Title: Build CI workflow for parser ML gate enforcement
2. Priority: P0
3. Owner: DevOps Engineer
4. Estimate: 2 days
5. Dependencies: PARSER-011, PARSER-020, PARSER-030
6. Gate mapping: GL0, GL1, GL2
7. Description:
   1. Add pipeline jobs for fixtures, replay smoke, dual-run smoke, tests, guardrail smoke.
   2. Produce aggregate gate summary artifact.
8. Acceptance criteria:
1. CI blocks merge on GL0/GL1/GL2 critical failures.
2. `parsing_ci_gate_<build>.json` artifact generated.
3. CI runs day-bundle validator and fails build if validator fails.
9. Deliverables:
1. `.github/workflows/parser-ml-gate.yml`
10. Status: todo

### Ticket PARSER-041
1. Title: Create parser assist rollout and rollback runbooks
2. Priority: P0
3. Owner: Operations Owner
4. Estimate: 1.5 days
5. Dependencies: PARSER-040
6. Gate mapping: GL4
7. Description:
   1. Document rollout steps, flag toggles, monitoring checks.
   2. Document rollback triggers and exact execution sequence.
8. Acceptance criteria:
   1. Runbooks approved by operations and parser owner.
   2. Drill-ready procedures included.
9. Deliverables:
   1. `docs/operations/parser_assist_rollout_runbook_v1.md`
   2. `docs/operations/parser_assist_rollback_drill_v1.md`
10. Status: todo

### Ticket PARSER-042
1. Title: Execute rollback drill and prove <=10 minute recovery
2. Priority: P0
3. Owner: Operations Owner
4. Estimate: 1 day
5. Dependencies: PARSER-041
6. Gate mapping: GL4
7. Description:
   1. Simulate canary failure and rollback to parser_v1-only.
   2. Capture timings and validation evidence.
8. Acceptance criteria:
   1. Drill completed in <=10 minutes.
   2. Post-rollback verification replay passes.
9. Deliverables:
   1. Rollback drill report.
10. Status: todo

### Ticket PARSER-043
1. Title: Run 3 consecutive shadow runs for GL3 stability evidence
2. Priority: P0
3. Owner: Parser Engineer + Ops
4. Estimate: 2 days elapsed (execution + analysis)
5. Dependencies: PARSER-032, PARSER-040
6. Gate mapping: GL3
7. Description:
   1. Execute three consecutive shadow runs.
   2. Verify invariants, guardrails, latency, abstain behavior each run.
8. Acceptance criteria:
1. All three runs satisfy GL3 criteria.
2. Evidence bundle and streak report complete.
3. Each shadow run includes authoritative stratified manual audit:
   1. minimum 24 accepted predictions per class,
   2. minimum 24 abstain predictions per class,
   3. total minimum audited rows per run = 192.
4. Proxy metrics alone are insufficient for GL3 pass.
5. Parent-guardrail metrics do not regress beyond configured budget vs frozen GL0 canonical baseline.
9. Deliverables:
   1. Shadow streak report.
10. Status: todo

### Ticket PARSER-044
1. Title: Controlled assist canary (5%) and GL5 launch review
2. Priority: P0
3. Owner: Product + Ops + Parser Owner
4. Estimate: 2 days elapsed (48h canary + review)
5. Dependencies: PARSER-043, PARSER-042
6. Gate mapping: GL5
7. Description:
   1. Launch assist mode for scoped edge-case classes only.
   2. Monitor quality, queue load, and incident profile for 48h.
8. Acceptance criteria:
1. Quality thresholds maintained for full canary window.
2. No Sev1/Sev2 attributable incidents.
3. Gate review outputs GO decision.
4. Parent-guardrail launch threshold profile is met for canary decision.
9. Deliverables:
   1. Canary report.
   2. Gate review signed memo.
10. Status: todo

## Dependency Summary (Critical Path)
1. `PARSER-001 -> PARSER-002 -> PARSER-003 -> PARSER-010 -> PARSER-011 -> PARSER-012 -> PARSER-013 -> PARSER-014`
2. `PARSER-011 -> PARSER-020 -> PARSER-021 -> PARSER-030 -> PARSER-031`
3. `(PARSER-014 + PARSER-020) -> PARSER-022 -> PARSER-023 -> PARSER-032 -> PARSER-043 -> PARSER-044`
4. `PARSER-040` must be live before GL2/GL3 evidence can be considered production-grade.
5. `PARSER-041 -> PARSER-042` must complete before any GL5 canary.

## Calendar Alignment (Binding)
1. Day 1: `PARSER-001`
2. Day 2: `PARSER-002`, `PARSER-003` (start), `PARSER-010`, `PARSER-011` (start)
3. Day 3-4: `PARSER-003` (complete), `PARSER-011` (complete), `PARSER-012`
4. Day 5: `PARSER-014` tooling prep only
5. Day 6-10: `PARSER-012`, `PARSER-020`, `PARSER-021`, `PARSER-030` start, `PARSER-031` prep
6. Day 11-17: `PARSER-013`, `PARSER-014`, `PARSER-031` complete
7. Day 13-15: `PARSER-040` complete required for GL2 validity
8. Day 18: `PARSER-022`, `PARSER-023`, `PARSER-032`, `PARSER-041`
9. Day 19-21: `PARSER-043` (3 shadow runs)
10. Day 20: `PARSER-042`
11. Day 21-22: `PARSER-044` (5% canary for 48h + launch review)

## Suggested Initial Assignment
1. Parser Tech Lead: PARSER-001, PARSER-030, PARSER-031, PARSER-032, PARSER-043
2. Data/Adjudication Lead: PARSER-010, PARSER-012, PARSER-013
3. Data Engineer: PARSER-003, PARSER-011, PARSER-014
4. ML Engineer: PARSER-020, PARSER-021, PARSER-022, PARSER-023
5. DevOps Engineer: PARSER-040
6. Operations Owner: PARSER-041, PARSER-042
7. Program Owner/Product: PARSER-002, PARSER-044
