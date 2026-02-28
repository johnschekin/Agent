# Hybrid Parser/ML Program: Master Schedule (Consolidated)

Date:
- 2026-02-27

Sources merged:
1. `plans/hybrid_ml_parser_execution_plan_2026-02-27.md`
2. `plans/hybrid_ml_parser_day_by_day_checklist_2026-02-27.md`
3. `plans/hybrid_ml_parser_ticket_backlog_2026-02-27.md`
4. `plans/hybrid_ml_parser_implementation_clarifications_2026-02-27.md`

This is the single execution artifact for implementation sequencing.

## 0) Contract-First Operating Model (Binding)
Goal:
1. Eliminate interpretation drift between implementer and reviewer.
2. Make every day auditable by machine before human red-team review.

Required execution contract for every day `D`:
1. A single run folder exists: `artifacts/launch_run_<yyyy-mm-dd>_day<D>/`.
2. The run folder contains, at minimum:
   1. `day_run_manifest.json`
   2. `day_blocker_register.json`
   3. `day_gate_summary.json`
   4. `day_validator_report.json`
   5. `day_canonical_selection_policy.json` when `git.is_dirty=true`
3. Red-team review may begin only if:
   1. `day_validator_report.json.status == "pass"`, and
   2. validator exit code is `0`.
4. If `day_gate_summary.red_team_status` is `in_review` or `complete`, day bundle must include adversarial subagent red-team review artifact and manifest pointer.

Contract precedence:
1. This file defines sequencing and gate ownership.
2. `plans/hybrid_ml_parser_ticket_backlog_2026-02-27.md` defines ticket-level acceptance criteria.
3. `plans/hybrid_ml_parser_day_by_day_checklist_2026-02-27.md` defines daily operating steps.
4. `plans/hybrid_ml_parser_day_bundle_validator_spec_2026-02-27.md` defines executable validation rules.

## 1) Program Scope
Goal:
1. Ship parser_v2 + ML edge-case assist safely behind hard launch gates GL0-GL5.
2. Keep parser_v1 as fallback baseline until GL5 pass.

In-scope phases:
1. Baseline freeze + governance.
2. Manual adjudication and labeled dataset.
3. Stage A model training/calibration and solver integration.
4. Shadow validation streak and operational readiness.
5. 5% canary assist and launch review.

Out-of-scope by default:
1. Stage B lightweight encoder unless explicitly unlocked by GL2 failure path.
2. Breaking schema/API changes before GL5.

## 2) Hard Gate Contract (Binding)
1. `GL0` Baseline Integrity.
2. `GL1` Manual Label Quality.
3. `GL2` Offline Model Quality.
4. `GL3` Shadow Stability.
5. `GL4` Operations Readiness.
6. `GL5` Controlled Assist Launch.

Rules:
1. Failing any gate blocks promotion.
2. Gate pass requires evidence artifact bundle and signed decision log.
3. No production assist without GL5 pass.

Parent-guardrail classification policy (binding):
1. At `GL0` (Day 0/Day 1 baseline freeze), parent-guardrail is a quality-debt signal, not a day-close blocker.
2. `GL0` fails only if:
   1. parent-guardrail artifact is missing/invalid, or
   2. provenance/canonical routing contract fails.
3. If parent-guardrail status is `fail` at GL0:
   1. record as open blocker with owner/ETA,
   2. classify as launch-blocking debt,
   3. proceed with day closure if validator contract passes.
4. At `GL2/GL3`, parent metrics become non-regression gates vs frozen GL0 canonical baseline.
5. At `GL5`, parent metrics must satisfy explicit launch thresholds (not just non-regression).

## 3) Ticket Set (Critical Path)
1. `PARSER-001 -> PARSER-002 -> PARSER-003 -> PARSER-010 -> PARSER-011 -> PARSER-012 -> PARSER-013 -> PARSER-014`
2. `PARSER-011 -> PARSER-020 -> PARSER-021 -> PARSER-030 -> PARSER-031`
3. `(PARSER-014 + PARSER-020) -> PARSER-022 -> PARSER-023 -> PARSER-032 -> PARSER-043 -> PARSER-044`
4. `PARSER-040` must be complete before any GL2/GL3 evidence is accepted.
5. `PARSER-041 -> PARSER-042` must be complete before GL5 canary execution.

## 4) Runtime and Data Constraints (Binding)
1. Parser_v2 status fields are sidecar-only through GL2.
2. GL3 may persist into dedicated shadow tables only.
3. Canonical persistence into production tables only after GL5 pass.
4. Assist authority is clause-level scoped overrides, with section-level fallback to v1 on abstain/high-risk.
5. Flag precedence is `CLI > ENV > config file > hardcoded defaults`.
6. GL1 requires:
   1. `>=800` total labels.
   2. `>=150` labels per in-scope edge-case class.

## 5) Master Calendar (22 Business Days)

## Week 1: Foundation + Governance + Labeling Start

### Day 1
1. Objective:
   1. Lock parser_v1 baseline and capture GL0 evidence.
2. Ticket focus:
   1. `PARSER-001`
3. Required work:
   1. Run fixture validation/replay.
   2. Run both guardrail scripts against baseline.
   3. Produce immutable baseline artifact bundle.
   4. If parent guardrail fails, open launch-blocking debt item in blocker register; do not block day closure solely on that fail.
4. Day output:
   1. GL0 baseline bundle.
   2. Signed baseline memo.
   3. `day_validator_report.json` pass.

### Day 2
1. Objective:
   1. Establish governance template and adjudication protocol.
2. Ticket focus:
   1. `PARSER-002`
   2. `PARSER-003` (start)
   3. `PARSER-010`
   4. `PARSER-011` (start)
3. Day output:
   1. Gate review template draft.
   2. Adjudication protocol v1 draft.
   3. Validator implementation spec accepted.
   4. `day_validator_report.json` pass.

### Day 3
1. Objective:
   1. Complete adjudication validator and start batch labeling.
2. Ticket focus:
   1. `PARSER-003` (complete)
   2. `PARSER-011` (complete)
   3. `PARSER-012` (start)
3. Day output:
   1. Validator pass/fail report.
   2. First major adjudication batch validated.
   3. `day_validator_report.json` pass.

### Day 4
1. Objective:
   1. Continue manual adjudication and first re-audit loop.
2. Ticket focus:
   1. `PARSER-012`
3. Day output:
   1. Re-audit report #1.
   2. Updated adjudication policy clarifications.
   3. `day_validator_report.json` pass.

### Day 5
1. Objective:
   1. Prepare data export/split tooling.
2. Ticket focus:
   1. `PARSER-014` tooling prep.
3. Day output:
   1. Export/split tooling draft.
   2. Week-1 gate status memo.
   3. `day_validator_report.json` pass.

## Week 2: Labeling Scale + Feature/Scoring Scaffolding

### Day 6
1. Objective:
   1. Continue labeling and build feature extraction skeleton.
2. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-020`
3. Day output:
   1. Feature extraction scaffold.

### Day 7
1. Objective:
   1. Continue labeling and implement scoring interface skeleton.
2. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-021`
3. Day output:
   1. Scoring interface + smoke tests.

### Day 8
1. Objective:
   1. Continue feature/scoring hardening with interim diagnostics.
2. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-020`
   3. `PARSER-021`
3. Day output:
   1. Interim diagnostics artifacts.

### Day 9
1. Objective:
   1. Continue solver integration preparation.
2. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-030` (prep)
3. Day output:
   1. Integration readiness report.

### Day 10
1. Objective:
   1. Start solver integration path and dual-run plumbing.
2. Ticket focus:
   1. `PARSER-012`
   2. `PARSER-030` (start)
   3. `PARSER-031` (prep only; dependency on `PARSER-030`)
3. Day output:
   1. First integration delta report.

## Week 3: GL1 Completion + GL2/CI Requirements

### Day 11
1. Objective:
   1. Push adjudication volume and consistency.
2. Ticket focus:
   1. `PARSER-013`
3. Day output:
   1. Re-audit report #2.

### Day 12
1. Objective:
   1. Continue adjudication quality pass and close policy gaps.
2. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-031` (start)
3. Day output:
   1. Label quality report v1.

### Day 13
1. Objective:
   1. Continue adapter contract integration and start CI gate hardening.
2. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-031`
   3. `PARSER-040` (start)
3. Day output:
   1. Adapter integration progress report v1.
   2. CI gate workflow draft.

### Day 14
1. Objective:
   1. Produce GL2 readiness packet.
2. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-040` (complete required)
3. Hard rule:
   1. GL2 pass claim is invalid if `PARSER-040` is not complete and active.
4. Day output:
   1. GL2 readiness packet.

### Day 15
1. Objective:
   1. Close GL1 volume/quality gap.
2. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-014` finalization prep.
3. Day output:
   1. Week-3 gate board.

## Week 4: Gate Closeout + Shadow/Ops Prep

### Day 16
1. Objective:
   1. Finalize training set candidate and label QA.
2. Ticket focus:
   1. `PARSER-013`
   2. `PARSER-014`
3. Day output:
   1. Training set v1-rc.

### Day 17
1. Objective:
   1. Complete GL1 evidence package.
2. Ticket focus:
   1. `PARSER-013` (complete)
   2. `PARSER-014` (complete)
3. Day output:
   1. GL1 pass packet.

### Day 18
1. Objective:
   1. Final offline GL2 decision, model/calibration closeout, dual-run closeout, and operations runbooks.
2. Ticket focus:
   1. `PARSER-022` (complete)
   2. `PARSER-023` (complete)
   3. `PARSER-032` (complete)
   4. `PARSER-041` (complete)
3. Day output:
   1. GL2 decision memo.
   2. Rollout/rollback runbooks.

### Day 19
1. Objective:
   1. Shadow streak run #1.
2. Ticket focus:
   1. `PARSER-043` run #1.
3. Day output:
   1. Shadow run #1 artifact bundle.

### Day 20
1. Objective:
   1. Shadow streak run #2 + rollback drill.
2. Ticket focus:
   1. `PARSER-043` run #2.
   2. `PARSER-042` (complete).
3. Day output:
   1. Shadow run #2 bundle.
   2. Rollback drill report (`<=10 min` target).

## Week 5: Final Shadow + Canary + Launch Decision

### Day 21
1. Objective:
   1. Shadow streak run #3 and open canary.
2. Ticket focus:
   1. `PARSER-043` run #3 (complete).
   2. `PARSER-044` (start).
3. Day output:
   1. GL3 pass/fail packet.
   2. Canary day-1 report.

### Day 22
1. Objective:
   1. Complete 48h canary and execute GL5 launch review.
2. Ticket focus:
   1. `PARSER-044` (complete).
3. Day output:
   1. GL5 canary report.
   2. Signed GO/NO-GO memo.

## 6) Gate Review Cadence
1. Weekly gate review:
   1. End of Week 1: GL0 + GL1 progress.
   2. End of Week 2: GL1 pace + GL2 pre-signal.
   3. End of Week 3: GL1 near-close + GL2 readiness.
   4. End of Week 4: GL1 close, GL2 close, GL3/GL4 prep.
   5. End of Week 5: GL5 decision.

## 7) Mandatory Daily Artifacts
1. Daily status log with:
   1. completed tickets,
   2. gate impact,
   3. blockers,
   4. artifact paths.
2. Effective config snapshot for any run.
3. Repro command list for each metric-producing job.
4. Machine-readable validator report:
   1. `day_validator_report.json`
   2. includes failing checks with actionable reason codes.
5. Canonical routing proof when workspace dirty:
   1. `day_canonical_selection_policy.json`
   2. manifest pointers routed to canonical outputs only.
6. Blocker register with lifecycle fields:
   1. `status in {open,re-attributed,closed}`
   2. `resolution` and `resolution_evidence[]` required when closed.

## 8) Master Exit Criteria
1. GL0-GL5 all passed with linked evidence.
2. Critical path tickets complete.
3. Canary window meets quality and incident thresholds.
4. Rollback drill verified within RTO target.
5. Launch memo signed by required roles.

## 9) Pre-Red-Team Validator Gate (Binding)
Validator source of truth:
1. `plans/hybrid_ml_parser_day_bundle_validator_spec_2026-02-27.md`

Required command shape (profile-driven):
1. `python3 scripts/validate_day_bundle.py --run-dir <day_run_dir> --day-id day<N> --profile <profile_json> --strict --json-out <day_validator_report.json>`

Gate policy:
1. If validator exit code is non-zero, implementation day is automatically `NO-GO`.
2. Human red-team findings cannot close a day that failed validator checks.
3. Day bundle closure requires both:
   1. validator pass,
   2. reviewer sign-off memo referencing validator report hash.
4. Day 0/Day 1 special rule:
   1. parent-guardrail `fail` does not force day closure fail when contract checks pass and debt is registered.
   2. missing parent-guardrail artifact still forces day closure fail.
