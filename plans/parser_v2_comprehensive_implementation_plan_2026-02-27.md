# Parser V2 Comprehensive Implementation Plan
Date: 2026-02-27  
Owner: Parsing Program (Agent)  
Status: Proposed (implementation-ready)  
Scope: Clause parsing refactor from coupled heuristics to constraint-driven parsing with explicit abstention.

## 1) Executive Summary
This plan replaces the current coupled-heuristic parser evolution model with a layered `parser_v2` architecture:
1. Text normalization
2. Enumerator lexer
3. Candidate graph builder
4. Global constraint solver
5. Confidence and abstention
6. Linking adapter contract

Migration is dual-run and reversible:
1. Keep parser_v1 in production.
2. Run parser_v2 in shadow mode against fixtures and corpus samples.
3. Cut over only after SLO gates pass.
4. Maintain instant rollback flag.

## 2) Goals and Non-Goals
### 2.1 Goals
1. Achieve deterministic globally consistent clause trees on known edge families.
2. Make ambiguity first-class with explicit abstain reasons.
3. Reduce whack-a-mole local heuristic coupling.
4. Preserve backward-compatible linking outputs during migration.
5. Use one fixture program for both parser QA and future ML/LLM.

### 2.2 Non-Goals
1. No ontology taxonomy redesign in this program.
2. No front-end redesign beyond required status/reason visibility.
3. No forced immediate parser_v1 deletion.
4. No full corpus rebuild as a precondition for every iteration.

## 3) Target Architecture (Parser V2)
### 3.1 Layer 0: Text Normalization
Responsibility:
1. Produce stable normalized text and mapping to source offsets.
2. Preserve reversible offset maps for highlighting and linking.
3. Emit normalization diagnostics (flattening, OCR noise indicators).

Outputs:
1. `NormalizedText` payload with raw-to-normalized span maps.
2. `normalization_flags` used by later abstain reasoning.

### 3.2 Layer 1: Enumerator Lexer
Responsibility:
1. Tokenize enumerators with rich lexical metadata.
2. Emit all plausible interpretations for ambiguous labels.
3. Preserve typography/anchor context at token level.

Token fields (minimum):
1. `token_id`
2. `raw_label`
3. `position_start`, `position_end`
4. `line_index`, `column_index`
5. `is_line_start`, `indentation_score`
6. `candidate_types` (alpha, roman, caps, numeric)
7. `ordinal_by_type`
8. `xref_context_features`
9. `layout_features`

### 3.3 Layer 2: Candidate Graph Builder
Responsibility:
1. Construct a directed acyclic candidate graph of node interpretations and parent edges.
2. Separate hard constraints from soft preferences.
3. Encode alternatives without committing early.

Graph entities:
1. `ClauseNodeCandidate` (token + type interpretation)
2. `ParentEdgeCandidate` (child candidate -> parent candidate or root)
3. `EdgeFeatures` (anchor compatibility, sibling sequence consistency, xref risk, span consistency)

### 3.4 Layer 3: Global Constraint Solver
Responsibility:
1. Select a globally consistent tree, not local greedy choices.
2. Enforce hard constraints.
3. Maximize weighted objective for soft consistency.

Hard constraints:
1. Exactly one interpretation per token selected or abstained.
2. Exactly one parent edge per selected node (or root).
3. Parent existence and acyclic ancestry.
4. Span ordering and no invalid sibling crossings.
5. Depth monotonicity and legal transitions.

Soft objective (weighted):
1. Anchor alignment.
2. Ordinal continuity.
3. Xref penalty.
4. Layout/indentation coherence.
5. Continuation plausibility.
6. Sibling-run coherence.

Solver strategy:
1. MVP: constrained beam/DP solver with deterministic tie-breaks.
2. Optional P2: ILP/CP backend (`ortools`) behind feature flag for parity experiments.

### 3.5 Layer 4: Confidence and Abstention
Responsibility:
1. Compute confidence from margin and structural evidence after solving.
2. Determine node-level and section-level status.
3. Emit machine-readable abstain reasons.

Statuses:
1. `accepted`
2. `review`
3. `abstain`

Node-level reason codes (minimum):
1. `low_margin`
2. `xref_conflict`
3. `parent_conflict`
4. `depth_conflict`
5. `span_conflict`
6. `layout_uncertain`
7. `normalization_noise`

Section-level policy:
1. Escalate section to `review`/`abstain` when critical-node abstention exceeds calibrated threshold.
2. Keep accepted subtree nodes available for linking where safe.

### 3.6 Layer 5: Linking Contract Adapter
Responsibility:
1. Emit parser_v2 output in stable schema for existing link/review systems.
2. Add new fields without breaking existing consumers.
3. Map abstentions into workflow queues.

Adapter output (minimum):
1. Existing clause fields (`clause_id`, `parent_id`, `depth`, spans, structural flags).
2. `parse_status`
3. `abstain_reason_codes`
4. `solver_margin`
5. `parser_version`
6. `parse_run_id`

## 4) Data Contracts and Schema Changes
### 4.1 New Internal Contracts
1. `docs/contracts/parser-v2-tokens-v1.md`
2. `docs/contracts/parser-v2-candidate-graph-v1.md`
3. `docs/contracts/parser-v2-solution-v1.md`
4. `docs/contracts/parser-v2-status-v1.md`

### 4.2 Storage Changes (Backward-Compatible)
1. Keep current clause storage contract for parser_v1.
2. Add parser_v2 sidecar tables for dual-run:
3. `clause_nodes_v2`
4. `clause_parse_runs_v2`
5. `clause_abstentions_v2`
6. Add mapping table: `clause_v1_v2_alignment`.

### 4.3 Linking Integration Fields
1. Add `parse_status` and `abstain_reason_codes` to candidate/link evidence payloads.
2. Ensure `policy_reasons` in link authority/evidence contracts can include parser abstain reasons.
3. Exclude abstained nodes from auto-link apply path by policy.

## 5) Program Workstreams
### WS-A: Core Parser V2 Engine
Deliverables:
1. `src/agent/parser_v2/` package
2. Lexer, graph builder, solver, confidence modules
3. Deterministic run orchestration and telemetry

### WS-B: Fixture and Adjudication Program
Deliverables:
1. Gold fixture lifecycle v1.0 (seed, validate, adjudicate, freeze)
2. P0 queue execution and adjudication throughput
3. Replay gate and fixture drift controls

### WS-C: Dual-Run and Shadow Evaluation
Deliverables:
1. Side-by-side runner
2. Delta reports by category and by contract field
3. Guardrail integration (parent-loss, collision, parser-integrity)

### WS-D: Linking Adapter and UI Contract
Deliverables:
1. Parser status mapping in linking APIs
2. UI-visible abstain reasons
3. Review queue routing for abstained nodes

### WS-E: CI and Release Controls
Deliverables:
1. Parser replay gate in CI
2. Shadow regression gates for dual-run
3. Cutover playbook and rollback switch

## 6) Migration Plan and Milestones
## M0: Program Freeze and Baseline Lock (1 week)
Deliverables:
1. Freeze parser_v1 behavior baseline.
2. Freeze fixture and guardrail baselines.
3. Publish parser_v2 plan and contracts.

Exit criteria:
1. No untracked parser_v1 logic changes.
2. Baseline artifacts versioned.

## M1: Foundations (2 weeks)
Deliverables:
1. Invariant validator integrated in parser tests.
2. Gold fixture replay gate operational in quick CI.
3. Adjudication queue framework active.

Exit criteria:
1. CI gates green on main parser baseline.
2. Fixture governance process documented.

## M2: Lexer + Token Model (2 weeks)
Deliverables:
1. `parser_v2.normalization` and `parser_v2.lexer`.
2. Token stream fixtures with deterministic outputs.
3. Token contract docs finalized.

Exit criteria:
1. Lexer determinism tests pass.
2. Token schema stable and versioned.

## M3: Candidate Graph Builder (2 weeks)
Deliverables:
1. Graph generation from token stream.
2. Hard/soft feature extraction for candidate edges.
3. Graph diagnostics and explainability tooling.

Exit criteria:
1. Candidate graph generated for all replay fixtures.
2. Zero hard-constraint construction failures on fixture set.

## M4: Solver MVP + Status Layer (3 weeks)
Deliverables:
1. Global solver (deterministic).
2. Confidence and abstention calibration module.
3. Node-level and section-level parse statuses.

Exit criteria:
1. Solver invariants pass at 100% on fixture suite.
2. Abstain reason taxonomy complete and emitted.

## M5: Adapter + Dual-Run Integration (2 weeks)
Deliverables:
1. Adapter to existing linking contract.
2. Dual-run pipeline storing v1 and v2 side-by-side.
3. Delta dashboards by category and reason codes.

Exit criteria:
1. Existing UI and APIs function with v1 unchanged.
2. v2 outputs available in shadow for review.

## M6: Shadow Hardening and Cutover Readiness (2 weeks)
Deliverables:
1. Category-level SLO report from dual-run.
2. Manual audit protocol completed on target slices.
3. Rollback playbook validated.

Exit criteria:
1. Cutover SLOs met for two consecutive runs.
2. Rollback drill passes.

## M7: Controlled Cutover (1 week)
Deliverables:
1. Feature flag switch to parser_v2 for production path.
2. Parser_v1 fallback retained.
3. Post-cutover monitoring with daily diff checks.

Exit criteria:
1. No SLO breach in stabilization window.
2. Go/no-go review signed off.

## 7) Acceptance Criteria (SLO Gates)
Cutover requires all:
1. Gold exact pass rate on non-ambiguous fixtures >= 99%.
2. Invariant violations = 0.
3. Parent-loss guardrail: no regression and target reduction window achieved.
4. High-letter false positives: significant reduction in fixtures and corpus shadow metrics.
5. Abstain rate within agreed operating band (initially 5-15% unless overridden).
6. Auto-link precision in human-audited sample >= 98%.

## 8) Calibration and Evaluation Design
### 8.1 Fixture Tiers
1. `accepted` tier: strict exact replay.
2. `review` tier: bounded tolerance.
3. `abstain` tier: abstain correctness and reason coherence.

### 8.2 Evaluation Slices
1. Heavy edge categories (`ambiguous_alpha_roman`, `high_letter_continuation`, `nonstruct_parent_chain`, `xref_vs_structural`).
2. Control categories (`linking_contract`, `defined_term_boundary`, `formatting_noise`).
3. Ontology-link contract slice for link precision impact.

### 8.3 Dual-Run Metrics
1. Tree structure parity
2. Status transitions (`accepted->review`, `review->abstain`, etc.)
3. Clause path changes impacting linking
4. Reason-code distribution shift

## 9) Rollout and Rollback
### 9.1 Rollout
1. Dark launch parser_v2 output storage only.
2. Enable parser_v2 for internal review-mode paths.
3. Enable parser_v2 for auto-link candidate generation behind flag.
4. Full cutover after SLO signoff.

### 9.2 Rollback
1. Single config flag to switch read/write path back to parser_v1.
2. Preserve parser_v2 artifacts for postmortem.
3. Automated alert on SLO breach triggers rollback recommendation.

## 10) Risks and Mitigations
Risk: Solver complexity and runtime overhead.  
Mitigation:
1. Start with scoped MVP categories.
2. Cache tokenization and graph features.
3. Use deterministic beam constraints before optional ILP.

Risk: Over-abstention reduces link throughput.  
Mitigation:
1. Calibrate abstain thresholds from adjudicated fixtures.
2. Tiered confidence policy by category.
3. Track queue burden weekly.

Risk: Contract drift between parser and linking pipeline.  
Mitigation:
1. Adapter contract tests.
2. Side-by-side payload diff tooling.
3. Fail-fast on contract mismatch.

Risk: Regression hidden by aggregate metrics.  
Mitigation:
1. Decision/category budgets in replay gate.
2. Per-category fixture gates.
3. Manual audit slices before cutover.

## 11) Team Structure and Ownership
1. Parser Core Lead: WS-A, solver and invariants.
2. Data/Quality Lead: WS-B, adjudication and calibration.
3. Platform Lead: WS-C and WS-E dual-run, CI, release controls.
4. Linking Integration Lead: WS-D adapter and UI contract.

## 12) Immediate Next 10 Working Days
1. Freeze and publish contracts for parser_v2 tokens, graph, status.
2. Scaffold `src/agent/parser_v2` modules and deterministic run harness.
3. Implement lexer/token contract tests.
4. Implement candidate graph builder with explainability dumps.
5. Add dual-run writer with v2 sidecar schema.
6. Execute first shadow run on replay smoke + P0 adjudication sample.
7. Review first calibration report and finalize abstain policy v1.

## 13) Deliverable Checklist
1. `plans/parser_v2_comprehensive_implementation_plan_2026-02-27.md`
2. `docs/contracts/parser-v2-tokens-v1.md`
3. `docs/contracts/parser-v2-candidate-graph-v1.md`
4. `docs/contracts/parser-v2-solution-v1.md`
5. `docs/contracts/parser-v2-status-v1.md`
6. `src/agent/parser_v2/*`
7. `scripts/run_parser_dual_shadow.py`
8. `scripts/eval_parser_v2_vs_v1.py`
9. `tests/test_parser_v2_*`
10. Cutover and rollback playbooks.
