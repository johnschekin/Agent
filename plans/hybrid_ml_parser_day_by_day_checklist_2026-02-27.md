# Hybrid Parser/ML Program: Day-by-Day Execution Checklist

Source of truth plan:
- `plans/hybrid_ml_parser_master_schedule_2026-02-27.md`
- `plans/hybrid_ml_parser_day_bundle_validator_spec_2026-02-27.md`

Scope:
- This checklist operationalizes GL0-GL5 with daily tasks, explicit outputs, and checkpoints.
- Duration: 5 weeks (22 business days).

Working assumptions:
1. Parser v1 remains production baseline throughout.
2. Parser v2 + ML scorer runs in shadow until GL5 canary.
3. No production assist promotion without gate evidence artifacts.

Reconciliation rules (binding with ticket backlog):
1. Day-by-day checklist is authoritative for calendar sequencing.
2. Ticket backlog is authoritative for scope, owners, dependencies, and acceptance criteria.
3. A task is only considered complete when both:
   1. checklist day output is produced, and
   2. corresponding ticket acceptance criteria are met.
4. A day cannot be marked complete before pre-red-team validator pass.

Daily close protocol (mandatory, every day):
1. Assemble day bundle under `artifacts/launch_run_<yyyy-mm-dd>_day<N>/`.
2. Run pre-red-team validator:
   1. `python3 scripts/validate_day_bundle.py --run-dir <day_run_dir> --day-id day<N> --profile <profile_json> --strict --json-out <day_run_dir>/day_validator_report.json`
3. If validator fails (non-zero exit), day status remains `NO-GO` and red-team is blocked.
4. If validator passes, proceed to red-team review.
5. EOD red-team analysis must be executed by adversarial subagent and artifacted in the day bundle when `red_team_status` advances to `in_review|complete`.
6. Red-team findings must update:
   1. `day_blocker_register.json`,
   2. `day_gate_summary.json`,
   3. `day_run_manifest.json` (when routing/provenance changes).
7. Day 0/Day 1 exception:
   1. parent-guardrail `fail` is logged as launch-blocking debt, not day-close failure.
   2. missing parent-guardrail artifact is still a hard failure.

## Canonical Ticket-to-Day Map (Binding)
1. Day 1: `PARSER-001`
2. Day 2: `PARSER-002`, start `PARSER-003`, `PARSER-010`, start `PARSER-011`
3. Day 3: complete `PARSER-003`, complete `PARSER-011`, start `PARSER-012`
4. Day 4: `PARSER-012`
5. Day 5: `PARSER-014` prep (depends on `PARSER-013` completion later; tooling only this day)
6. Day 6-10: `PARSER-012` continuation + `PARSER-020`, `PARSER-021` scaffolding
7. Day 11-17: `PARSER-013`, complete `PARSER-014`, complete `PARSER-030`, then start `PARSER-031`
8. Day 13-15: `PARSER-040` must be completed before claiming GL2 gate pass
9. Day 18: `PARSER-022`, `PARSER-023`, `PARSER-032`, `PARSER-041`
10. Day 19-21: `PARSER-043` (three consecutive shadow runs)
11. Day 20: `PARSER-042`
12. Day 21-22: `PARSER-044` (48h canary + launch review)

## Week 1 (Foundation + Labeling System)

### Day 1
1. Lock scope and create run folder structure under `artifacts/launch_run_<date>/`.
2. Validate current fixture schema and replay baseline parser:
   1. `python3 scripts/validate_gold_fixtures.py --fixtures data/fixtures/gold/v1/fixtures.jsonl`
   2. `python3 scripts/replay_gold_fixtures.py --fixtures data/fixtures/gold/v1/fixtures.jsonl`
3. Snapshot baseline guardrails:
   1. `python3 scripts/edge_case_clause_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_guardrail_baseline.json`
   2. `python3 scripts/edge_case_clause_parent_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json`
4. Output:
   1. GL0 baseline artifact bundle.
   2. `day_validator_report.json` pass.
   3. If parent guardrail fails, blocker register includes launch-blocking debt entry with owner/ETA and remediation hypothesis.
5. Ticket focus:
   1. `PARSER-001`

### Day 2
1. Finalize manual adjudication protocol doc.
2. Implement/verify adjudication log schema validator.
3. Start manual adjudication batch #1 (20 rows, full rationale per row).
4. Output:
   1. Protocol v1 draft.
   2. First validated adjudication log batch.
   3. Validator implementation spec signed.
   4. `day_validator_report.json` pass.
5. Ticket focus:
   1. `PARSER-002`
   2. `PARSER-003` (start)
   3. `PARSER-010`
   4. `PARSER-011` (start)

### Day 3
1. Adjudicate batches #2 and #3 (40 rows).
2. Run schema validation and completeness checks.
3. Add re-audit workflow script scaffolding.
4. Output:
   1. 60 total adjudicated rows.
   2. Validator results and defects list.
   3. `day_validator_report.json` pass.
5. Ticket focus:
   1. `PARSER-003` (complete)
   2. `PARSER-011` (complete)
   3. `PARSER-012` (start)

### Day 4
1. Adjudicate batches #4 and #5 (40 rows).
2. Run 10% re-audit sample from current pool.
3. Resolve policy ambiguities; update adjudication protocol.
4. Output:
   1. 100 total rows.
   2. Re-audit consistency report #1.
   3. `day_validator_report.json` pass.
5. Ticket focus:
   1. `PARSER-012`

### Day 5
1. Build initial export/split scripts for ML training datasets.
2. Generate first train/val/holdout split (doc_id-separated).
3. Weekly checkpoint against GL1 progress and GL0 integrity.
4. Output:
   1. Dataset split artifact v0.
   2. Weekly status memo with blockers.
   3. `day_validator_report.json` pass.
5. Ticket focus:
   1. `PARSER-014` tooling prep only (final export waits on `PARSER-013`)

## Week 2 (Scale Labeling + Feature/Model Baseline)

### Day 6
1. Adjudicate 40 additional rows (batches #6-#7).
2. Implement parser_v2 feature extraction scaffold.
3. Add unit tests for feature determinism.
4. Output:
   1. 140 total rows.
   2. Feature scaffold PR-ready diff.
5. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-020`

### Day 7
1. Adjudicate 40 additional rows.
2. Implement ML scoring interface with deterministic fallback.
3. Add scoring smoke tests.
4. Output:
   1. 180 total rows.
   2. Scoring interface tests.
5. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-021`

### Day 8
1. Adjudicate 40 additional rows.
2. Continue ML feature/scoring hardening and dry-run diagnostics.
3. Generate interim diagnostics report.
4. Output:
   1. 220 total rows.
   2. Interim diagnostics artifact bundle v0.
5. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-020`
   3. `PARSER-021`

### Day 9
1. Adjudicate 40 additional rows.
2. Continue solver integration preparation and integration tests.
3. Integrate threshold scaffolding for later calibration.
4. Output:
   1. 260 total rows.
   2. Integration readiness report v0.
5. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-030` (prep)

### Day 10
1. Adjudicate 40 additional rows.
2. Integrate scorer in parser_v2 solver behind flags.
3. Run parser_v2 dual-run on canonical fixture pack.
4. Weekly checkpoint:
   1. GL0 still green.
   2. GL1 progress.
   3. GL2 early signal (not gate pass yet).
5. Output:
   1. 300 total rows.
   2. First dual-run delta report.
6. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-030` (start)
   3. `PARSER-031` (prep only; dependency on `PARSER-030`)

## Week 3 (GL1 Completion + GL2 Quality Push)

### Day 11
1. Adjudicate 60 rows.
2. Run re-audit on random 10% sample.
3. Tighten labels/policy where disagreement exists.
4. Output:
   1. 360 total rows.
   2. Re-audit report #2.
5. Ticket focus:
   1. `PARSER-013`

### Day 12
1. Adjudicate 60 rows.
2. Continue adjudication quality pass and close policy gaps.
3. Prepare model-ready export requirements.
4. Output:
   1. 420 total rows.
   2. Label quality report v1.
5. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-031` (start)

### Day 13
1. Adjudicate 60 rows.
2. Improve features for top two persistent failure categories.
3. Continue adapter contract integration work.
4. Implement CI gate workflow and enforce GL2 precondition.
5. Output:
   1. 480 total rows.
   2. Adapter integration progress report v1.
   3. CI gate workflow artifact.
6. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-031`
   3. `PARSER-040` (start)

### Day 14
1. Adjudicate 80 rows.
2. Run fixed evaluation protocol (all required commands from Section 11).
3. Generate GL2 readiness summary.
4. GL2 pass claim is valid only if `PARSER-040` is completed and active.
5. Output:
   1. 560 total rows.
   2. GL2 readiness packet v1.
6. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-040` (complete)

### Day 15
1. Adjudicate 80 rows.
2. Re-audit 10% sample; enforce consistency threshold.
3. Weekly checkpoint:
   1. Assess GL1 path-to-pass (>=800 rows target).
   2. Assess GL2 proximity.
4. Output:
   1. 640 total rows.
   2. Week-3 gate board.
5. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-014` (finalize once labels are complete enough)

## Week 4 (Gate Closeout + Shadow Streak + Ops Readiness)

### Day 16
1. Adjudicate 80 rows.
2. Validate full log completeness and rationale quality.
3. Finalize training set v1 candidate.
4. Output:
   1. 720 total rows.
   2. Training set v1-rc1.
5. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-014`

### Day 17
1. Adjudicate final 80 rows to hit GL1 minimum.
2. Run GL1 evidence package generation:
   1. count, completeness, re-audit consistency, escalation rate.
3. Retrain model on full v1 set.
4. Output:
   1. 800+ total rows.
   2. GL1 pass packet.
5. Ticket focus:
   1. `PARSER-013` (complete)
   2. `PARSER-014` (complete)

### Day 18
1. Run full offline evaluation for GL2.
2. If GL2 thresholds fail, perform one targeted iteration (features/calibration).
3. Freeze model artifact candidate for shadow.
4. Finalize operations runbooks.
5. Output:
   1. GL2 decision memo (pass/fail with evidence).
   2. Operations runbooks v1.
6. Ticket focus:
   1. `PARSER-022` (start and complete)
   2. `PARSER-023` (start and complete)
   3. `PARSER-032` (complete)
   4. `PARSER-041` (complete)

### Day 19
1. Run shadow cycle #1 with parser_v2 ML scorer (no production impact).
2. Run invariant and guardrail checks.
3. Collect latency and abstain-rate data.
4. Output:
   1. Shadow evidence bundle run #1.
5. Ticket focus:
   1. `PARSER-043` run #1

### Day 20
1. Run shadow cycle #2.
2. Execute rollback drill and collect RTO evidence.
3. Prepare interim gate package for GL3/GL4.
4. Output:
   1. Shadow evidence bundle run #2.
   2. Rollback drill report.
5. Ticket focus:
   1. `PARSER-043` run #2
   2. `PARSER-042` (complete)

## Week 5 (Canary Execution + Final Gate)

### Day 21
1. Run shadow cycle #3 and finalize GL3 evidence.
2. Start controlled assist canary at 5% (48h window start).
3. Monitor quality thresholds and review queue throughput continuously.
4. Output:
   1. GL3 pass/fail packet.
   2. Canary day-1 report.
5. Ticket focus:
   1. `PARSER-043` run #3 (complete)
   2. `PARSER-044` (start)

### Day 22
1. Complete 48h canary window.
2. Run GL5 launch decision review with full evidence bundle.
3. Publish GO/NO-GO memo and next-step rollout plan.
4. Output:
   1. GL5 canary report.
   2. Signed launch decision memo.
5. Ticket focus:
   1. `PARSER-044` (complete)

## Daily Standup Template (Use Every Day)
1. Yesterday completed:
2. Today planned:
3. Blockers:
4. Gate impact (GL0-GL5):
5. Artifact paths produced:
6. Validator status and report path:

## Exit Criteria by End of Checklist
1. GL0 through GL5 passed with linked evidence artifacts.
2. `PARSER-001` through `PARSER-044` required critical-path tickets completed.
3. Any failed gate has explicit remediation owner/date and blocks production assist.
