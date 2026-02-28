# Hybrid Parser/ML Program: Day-Bundle Validator Spec

Date:
1. 2026-02-27

Status:
1. Binding execution contract for all daily bundles.

## 1) Purpose
1. Prevent red-team churn caused by ambiguous or incomplete evidence packets.
2. Enforce a machine-checkable Definition of Done before human review.
3. Standardize day-level provenance, routing, gate status, and blocker lifecycle checks.

## 2) Validator CLI Contract
Command:
1. `python3 scripts/validate_day_bundle.py --run-dir <day_run_dir> --day-id day<N> --profile <profile_json> --strict --json-out <day_run_dir>/day_validator_report.json`

Required arguments:
1. `--run-dir`: day bundle folder.
2. `--day-id`: `day1` through `day22`.
3. `--profile`: profile file defining required artifacts/assertions.
4. `--json-out`: output report path.

Optional arguments:
1. `--allow-warn-only`: demote non-critical checks from fail to warn.
2. `--repo-root`: override repository root for path checks.

Exit codes:
1. `0`: pass.
2. `2`: contract violation (missing artifact, failed assertion, mismatch).
3. `3`: invalid input/profile/schema parse failure.
4. `4`: internal validator error.

## 3) Required Day-Bundle Artifacts
Every day bundle must include:
1. `day_run_manifest.json`
2. `day_blocker_register.json`
3. `day_gate_summary.json`
4. `day_validator_report.json` (validator output)
5. `command_log.txt` or equivalent command list artifact
6. `artifact_index.json` listing all produced artifacts and hashes

Conditional required artifacts:
1. If `day_run_manifest.git.is_dirty == true`:
   1. `day_canonical_selection_policy.json`
   2. canonical output folder (for example `canonical/`)
   3. manifest primary pointers routed only to canonical outputs
2. If a blocker is marked `closed`:
   1. `resolution`
   2. `resolved_at`
   3. non-empty `resolution_evidence[]`
3. If `day_gate_summary.red_team_status` is `in_review` or `complete`:
   1. adversarial subagent red-team artifact JSON
   2. manifest output pointer to that artifact

Blocker schema requirements:
1. Each blocker entry must include `blocking_scope`:
   1. `day_close` for immediate day-closure blockers.
   2. `launch` for deferred launch blockers.

## 4) Report Output Schema
`day_validator_report.json` must contain:
1. `schema_version`
2. `generated_at`
3. `day_id`
4. `run_dir`
5. `status` (`pass|fail`)
6. `summary`:
   1. `total_checks`
   2. `passed`
   3. `failed`
   4. `warnings`
7. `checks[]`:
   1. `check_id`
   2. `severity` (`critical|high|medium|low`)
   3. `status` (`pass|fail|warn`)
   4. `message`
   5. `artifact_path` (if applicable)
   6. `expected`
   7. `actual`
8. `failed_check_ids[]`
9. `warnings[]`

## 5) Core Validation Checks
Critical checks (must pass):
1. `VAL-FILE-001`: all required files exist.
2. `VAL-JSON-001`: required JSON artifacts parse successfully.
3. `VAL-MANIFEST-001`: manifest has required keys (`git`, `parser`, `inputs`, `command_exit_codes`, `output_artifacts`).
4. `VAL-INDEX-001`: `artifact_index.json` paths exist and index SHA256 values match on-disk bytes.
5. `VAL-HASH-001`: declared artifact hashes in manifest match actual file hashes.
6. `VAL-EXIT-001`: manifest `command_exit_codes` match corresponding `.exit_code` files.
7. `VAL-GATE-001`: gate summary status is logically consistent with canonical outputs.
8. `VAL-BLOCKER-001`: blockers use allowed lifecycle states and closure fields when closed.
9. `VAL-BLOCKER-002`: blockers include valid `blocking_scope`.
10. `VAL-REDTEAM-001`: no red-team execution allowed when validator status is `fail`.
11. `VAL-REDTEAM-002`: when red-team status is `in_review|complete`, require adversarial subagent review artifact with valid schema and manifest pointer.

Conditional critical checks:
1. `VAL-CANON-001`: if workspace dirty, canonical policy file exists.
2. `VAL-CANON-002`: if workspace dirty, primary output pointers map to canonical artifacts.
3. `VAL-CANON-003`: dirty outputs are explicitly flagged diagnostic-only and not primary.
4. `VAL-ADJ-SYNTH-001`: synthetic-write patterns are forbidden, protected adjudication artifacts (`manual_adjudication_batch*.jsonl`, `manual_reasoning*.jsonl`, queue updates) cannot be touched by non-allowlisted scripting commands, and command log must include adjudication lineage attestation entries (`MANUAL_ADJUDICATION_ATTESTATION batch_id=<...>`).

High-priority checks:
1. `VAL-CONSIST-001`: memo claims match machine outputs (status, counts, exit codes).
2. `VAL-TIME-001`: artifact timestamps are non-decreasing for latest revision fields.
3. `VAL-PROV-001`: commit SHA alignment between manifest and clean-source evidence.
4. `VAL-GL0-PARENT-001`: at GL0/day1, parent-guardrail `fail` requires open launch-scoped blocker with owner/ETA/hypothesis.

## 6) Day Profile System
Profiles live under:
1. `config/day_bundle_validator/`

Profile contract:
1. Define required artifacts by day.
2. Define required checks by gate stage.
3. Define allowed warnings.
4. Define extra checks (for example GL3 manual-audit sample minimums).

Recommended starter profiles:
1. `day1_gl0_profile.json`
2. `day2_day5_governance_profile.json`
3. `day6_day17_gl1_gl2_profile.json`
4. `day18_day22_gl2_gl5_profile.json`

## 7) Gate-Specific Add-ons
GL0:
1. Replay + clause guardrail + parent guardrail artifacts must exist.
2. Canonical source selection enforced when dirty.
3. Parent-guardrail `fail` does not fail day closure by itself.
4. Parent-guardrail `fail` must produce launch-scoped debt blocker entry.

GL1:
1. Label count and per-class minimums verified from adjudication artifacts.
2. Re-audit consistency and escalation metrics present.

GL2:
1. Model eval/calibration artifacts present.
2. Control-set degradation checks present and within threshold.
3. Parent-guardrail non-regression vs frozen GL0 canonical baseline must pass.

GL3:
1. 3-run shadow streak evidence present.
2. Manual stratified audit sample minimums present and satisfied.
3. Parent-guardrail non-regression must hold across all streak runs.

GL4:
1. Rollback drill report present with RTO validation.

GL5:
1. Canary report present.
2. Launch memo sign-off fields complete.
3. Parent-guardrail launch threshold profile must pass.

## 8) CI and Workflow Integration
1. CI must run validator for any PR that modifies:
   1. parser logic,
   2. guardrail scripts,
   3. gate plans,
   4. daily run artifacts.
2. CI should publish `day_validator_report.json` as a build artifact.
3. Merge is blocked when validator exits non-zero.

## 9) Operational Policy
1. No manual override for critical check failures.
2. Warning-only checks may be overridden only with explicit note in blocker register.
3. Rebaseline is forbidden unless explicitly authorized in gate policy and recorded in memo.
4. GL0 parent-guardrail fail is treated as launch debt; day closure may proceed only when debt is explicitly registered.
5. EOD red-team analysis must be executed through an adversarial subagent review artifact when red-team status advances to `in_review` or `complete`.

## 10) Definition of Done for This Spec
1. Validator implementation exists and passes its own tests.
2. Day profiles are versioned and referenced in daily checklist.
3. Master schedule and backlog reference this spec as binding.
