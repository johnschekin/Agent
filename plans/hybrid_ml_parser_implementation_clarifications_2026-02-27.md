# Hybrid Parser/ML: Implementation Clarifications (Binding)

Applies to:
- `plans/hybrid_ml_parser_execution_plan_2026-02-27.md`
- `plans/hybrid_ml_parser_day_by_day_checklist_2026-02-27.md`
- `plans/hybrid_ml_parser_ticket_backlog_2026-02-27.md`

Date:
- 2026-02-27

## Q2: Persist parser_v2 status fields now or sidecar-only until GL3?
Decision:
1. Sidecar-only through GL2.
2. At GL3 shadow, persist to dedicated shadow tables only (no mutation of canonical v1 clause/link tables).
3. Canonical table persistence is allowed only after GL5 pass.

Rationale:
1. Preserves rollback simplicity and avoids premature schema lock-in.

## Q3: Assist authority scope (v1 except scoped overrides)?
Decision:
1. Override authority is clause-level only, limited to approved edge-case classes.
2. Section-level safety override: if `section_parse_status=abstain` or critical abstain ratio exceeds threshold, fallback to v1 for the whole section.
3. Critical abstain ratio threshold is fixed at `0.40` for first release wave.

Rationale:
1. Minimizes blast radius while preserving section-level safety guard.

## Q4: Runtime flag source of truth and precedence
Decision:
1. Precedence order:
   1. CLI args (highest, only for scripts/jobs),
   2. environment variables,
   3. checked-in config file defaults,
   4. hardcoded defaults (lowest).
2. Every run writes an effective-config snapshot artifact.

Rationale:
1. Deterministic reproducibility with explicit override semantics.

## Q6: GL1 minimum label requirement
Decision:
1. Both constraints are required:
   1. global minimum >= 800 labeled rows,
   2. per-class minimum >= 150 rows for each of the four in-scope edge-case classes.

## Q7: Class balance target
Decision:
1. Target: 200 labels per class (4 classes, 800 total baseline).
2. Acceptable GL1 range: 150-250 per class.
3. Any class below 150 blocks GL1 pass.

## Q8: Where adjudication lives
Decision:
1. Adjudication is stored in a separate immutable, versioned adjudication log.
2. Queue rows remain operational state only and reference adjudication IDs.

Rationale:
1. Ensures auditability and reproducible training sets.

## Q9: Canonical source_snapshot_id
Decision:
1. Canonical ID format:
   1. `{corpus_build_id}:{section_text_sha256}`
2. Additional provenance fields are mandatory but separate:
   1. `doc_id`,
   2. `section_number`,
   3. `doc_text_sha256`,
   4. optional `fixture_snapshot_tag`.

## Q10: Token-level vs section-level label conflicts
Decision:
1. Token-level labels are authoritative for token/node training records.
2. Section-level labels are authoritative for section-status training targets.
3. If section label indicates full abstain/invalid section, token rows are excluded from accepted-token training export.

## Q11: Stage A model family and dependency constraints
Decision:
1. Stage A approved families:
   1. regularized logistic regression,
   2. tree ensemble via scikit-learn (HistGradientBoosting).
2. Dependency constraint:
   1. scikit-learn only for Stage A (no xgboost/lightgbm requirement in first wave).

## Q12: Stage B text encoder scope
Decision:
1. Stage B (lightweight text encoder) is deferred by default.
2. It is unlocked only if GL2 fails after one full Stage A iteration on labels/features/calibration.

## Q13: Solver margin definition
Decision:
1. Node-level `solver_margin` = top-1 candidate score minus top-2 candidate score for that token.
2. Section-level margin for reporting = `margin_abs` and `margin_ratio` from solver summary.

## Q14: Threshold calibration scope
Decision:
1. Thresholds are calibrated per edge-case class.
2. A global floor policy applies for safety:
   1. accepted precision floor,
   2. abstain precision floor.

## Q15: GL2 control set for <=1.5% degradation
Decision:
1. Control set is a fixed, versioned non-edge-case fixture pack (doc_id-disjoint from training/holdout).
2. Control pack must include representative clean sections across major document templates.
3. Degradation metric is computed against parser_v1 baseline on this fixed control pack.
4. Fixed control pack path: `data/fixtures/gold/v1/packs/v1-control-nonedge-1200/fixtures.jsonl`.
5. Fixed control set version ID: `v1-control-nonedge-1200@2026-02-27`.

## Q16: GL3 “GL2-level precision in shadow” audit authority
Decision:
1. Authoritative mechanism is stratified sampled manual audit per shadow run.
2. Proxy metrics are monitoring signals only, not sufficient for gate pass.
3. Minimum sample each run:
   1. 24 accepted predictions per in-scope class,
   2. 24 abstain predictions per in-scope class,
   3. total minimum audited rows per run = 192.

## Q17: Parent-guardrail baseline refresh timing
Decision:
1. Do not refresh/rebaseline immediately before GL0.
2. Any current regression vs baseline is treated as fail-to-investigate.
3. Rebaseline only after intentional release milestone with signed gate review.

## Q18: Contract versioning for API/storage payload changes
Decision:
1. Additive, backward-compatible fields may be introduced with minor contract revision docs.
2. Any breaking API/storage change requires explicit version bump and migration plan.
3. No in-place mutation/removal of existing required v1 fields during GL0-GL3 phases.

## Q19: Canonical GL3 shadow persistence tables
Decision:
1. Use dedicated shadow tables only during GL3:
   1. `parser_v2_shadow_runs`
   2. `parser_v2_shadow_sections`
   3. `parser_v2_shadow_nodes`
2. Canonical minimum schema:
   1. `parser_v2_shadow_runs`: `run_id`, `run_ts`, `parser_version`, `model_version`, `flags_json`, `config_hash`, `source_snapshot_id`.
   2. `parser_v2_shadow_sections`: `run_id`, `doc_id`, `section_number`, `section_key`, `section_parse_status`, `critical_node_abstain_ratio`, `margin_abs`, `margin_ratio`, `audit_required`.
   3. `parser_v2_shadow_nodes`: `run_id`, `doc_id`, `section_number`, `clause_id`, `parent_id`, `depth`, `parse_status`, `abstain_reason_codes_json`, `solver_margin`, `confidence_score`.
3. No writes to canonical production parse/link tables from these shadow tables before GL5.
