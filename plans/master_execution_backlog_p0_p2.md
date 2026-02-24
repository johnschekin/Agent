# Master Execution Backlog (P0/P1/P2)

This backlog implements `plans/master_rollout_plan.md`.

## Ticket Format

Each ticket contains:
- objective
- files to change
- implementation notes
- acceptance checks

## P0: Immediate Stability and Throughput

### P0-01 Plan and Gate Consolidation

Objective:
- make master plan authoritative and remove stale references.

Files:
- `plans/execution_backlog_p0_p2.md`
- `plans/pilot_protocol.md`
- `docs/ARCHITECTURE.md`
- `docs/BEGINNER_GUIDE.md`

Implementation notes:
- add explicit pointer to `plans/master_rollout_plan.md`
- remove references to non-authoritative execution docs

Acceptance checks:
- all active plan/docs reference master plan for gate order
- no stale active reference to `mvp_phase_a.md`

### P0-02 Ray Writer Backpressure and Flush Health

Status:
- DONE (2026-02-23): legacy writer-actor pipeline in `scripts/build_corpus_ray.py`
  now enforces bounded backpressure using explicit pending-call controls
  (`--writer-max-inflight`, `--writer-drain-chunk`, `--writer-progress-interval`),
  periodic writer-stage progress logging, pre-finalize writer-queue drain, and
  manifest diagnostics (`writer_drain_total`, `writer_peak_pending`).
- DONE (2026-02-23): v2 Parquet-sharded pipeline and correctness gate remain available
  in `scripts/build_corpus_ray_v2.py` and `scripts/check_corpus_v2.py`.

Objective:
- prevent long writer-drain tails after worker completion.

Files:
- `scripts/build_corpus_ray.py`

Implementation notes:
- add bounded in-flight writer submissions
- periodically inspect writer queue/batch length and throttle dispatch
- add explicit write-stage progress logs

Acceptance checks:
- on full run, writer finalize phase is bounded and predictable
- no unbounded queued writer tasks

### P0-03 Corpus Build Manifest and Snapshot Metadata

Status:
- DONE (2026-02-23): run manifests now emitted by
  `scripts/build_corpus_index.py`, `scripts/build_corpus_ray.py`, and
  `scripts/build_corpus_ray_v2.py`, with helper utilities in
  `src/agent/run_manifest.py`.
- Added manifest-aware profiling and comparison in `scripts/corpus_profiler.py`
  and manifest access in `src/agent/corpus.py`.

Objective:
- make every corpus build reproducible and traceable.

Files:
- `scripts/build_corpus_index.py`
- `scripts/build_corpus_ray.py`
- `scripts/corpus_profiler.py`
- `src/agent/corpus.py`

Implementation notes:
- emit `run_manifest.json` per build with:
  - run_id, input source, schema_version, commit hash (if available)
  - row counts by table
  - timings and error counts

Acceptance checks:
- each build writes manifest side-by-side with DB
- manifest can be used to compare two snapshots deterministically

### P0-04 Strategy Schema Alignment: Template Overrides

Status:
- DONE (2026-02-23): `template_overrides` is now dict-based in
  `src/agent/strategy.py` with backward loader compatibility for legacy tuple/list payloads.
- Integrated normalization in `scripts/strategy_writer.py` and
  `scripts/migrate_strategy_v1_to_v2.py`.

Objective:
- align runtime strategy schema with target dict-based template overrides.

Files:
- `src/agent/strategy.py`
- `scripts/migrate_strategy_v1_to_v2.py`
- `scripts/strategy_writer.py`
- `tests/test_strategy.py`

Implementation notes:
- migrate `template_overrides` from tuple format to `dict[str, dict]`
- keep backward loader compatibility for existing strategy files

Acceptance checks:
- old strategy json loads successfully
- new strategy json persists dict-based overrides
- strategy writer reads/writes without regression

### P0-05 Evidence Contract v2

Status:
- DONE (2026-02-23): `scripts/evidence_collector.py` now writes normalized
  `evidence_v2` rows with provenance fields (`ontology_node_id`, `run_id`,
  `strategy_version`, `source_tool`) and policy diagnostics
  (confidence/outlier/scope/preemption).
- DONE (2026-02-23): explicit `NOT_FOUND` support added for both
  pattern_tester-derived misses (`miss_records`) and child_locator no-match
  parents (`--emit-not-found`).
- Added/updated tests:
  `tests/test_evidence_collector.py`, `tests/test_child_locator.py`,
  `tests/test_integration.py`.

Objective:
- persist full provenance and policy outcomes for reviewable outputs.

Files:
- `scripts/evidence_collector.py`
- `scripts/pattern_tester.py`
- `scripts/child_locator.py`
- `tests/test_integration.py`

Implementation notes:
- include fields:
  - `ontology_node_id`
  - `run_id`
  - `strategy_version`
  - confidence breakdown
  - outlier flags
  - template family
  - scope/preemption diagnostics
- add explicit NOT_FOUND record support

Acceptance checks:
- evidence jsonl rows validate against v2 schema
- both hit and not_found records are emitted where applicable

### P0-06 Two-Stage Retrieval Skeleton

Objective:
- establish family candidate narrowing before concept scoring.

Status:
- DONE (2026-02-23): shared candidate-set loader added in
  `src/agent/corpus.py` and wired into both `scripts/pattern_tester.py`
  and `scripts/coverage_reporter.py`.
- DONE (2026-02-23): `coverage_reporter.py` now supports
  `--family-candidates-in` / `--family-candidates-out`,
  candidate-set pruning metrics, and provenance `run_id`.

Files:
- `scripts/pattern_tester.py`
- `scripts/coverage_reporter.py`
- `src/agent/corpus.py`
- `src/agent/textmatch.py`

Implementation notes:
- add optional family-candidate input/output paths
- support evaluate-concept-on-candidate-set mode

Acceptance checks:
- concept evaluation can run on candidate subset without code changes elsewhere
- output reports candidate set size and pruning ratio

### P0-07 Parser Anomaly Queue and Fallback Trigger

Objective:
- detect and recover from template parse blind spots.

Status:
- DONE (2026-02-23): parser fallback path added in `src/agent/section_parser.py`
  (regex fallback when `DocOutline` yields no sections), and integrated into both
  `scripts/build_corpus_index.py` and `scripts/build_corpus_ray.py`.
- DONE (2026-02-23): parse anomaly reports now emitted as
  `<output>.anomalies.json` (or `--anomaly-output`) with
  `{doc_id, template_family, failure_signatures, section_count, clause_count}`.
- DONE (2026-02-23): `scripts/corpus_profiler.py` now exposes structured anomaly
  detail lists (`no_sections_details`, `zero_clauses_details`) with signatures.

Files:
- `scripts/build_corpus_index.py`
- `scripts/build_corpus_ray.py`
- `scripts/corpus_profiler.py`
- `src/agent/section_parser.py`

Implementation notes:
- flag documents with `section_count=0` or `clause_count=0` into anomaly outputs
- add fallback parser path for flagged docs

Acceptance checks:
- anomaly report includes doc ids, template labels, and failure signatures
- rerun with fallback reduces blind-spot population

### P0-08 Benchmark Harness for Cost/Latency Budgeting

Objective:
- make performance and scaling costs measurable per tool and stage.

Status:
- DONE (2026-02-23): new `scripts/benchmark_pipeline.py` runs standardized
  sweeps for sample sizes (`100/500/5000` configurable), benchmarks
  `pattern_tester` and `child_locator`, and emits JSON + Markdown reports.
- DONE (2026-02-23): report schema now includes wall time, CPU time,
  docs/sec, and memory estimate (`ru_maxrss` delta) per tool/sample run.

Files:
- `scripts/benchmark_pipeline.py` (new)
- `scripts/pattern_tester.py`
- `scripts/child_locator.py`

Implementation notes:
- standardized benchmark output for sample sizes 100/500/5k
- include cpu time, wall time, docs per sec, and memory estimates

Acceptance checks:
- benchmark report generated in JSON and markdown
- baseline retained for regression comparison

## P1: Quality Hardening and Ontology Scale Preparation

### P1-01 Global Strategy Seeding for All Ontology Nodes

Objective:
- generate initial strategy files for full ontology coverage.

Status:
- DONE (2026-02-23): new `scripts/strategy_seed_all.py` generates seed
  strategies for every ontology node id with source tagging
  (`bootstrap`/`derived`/`empty`) and optional per-node file emission.
- DONE (2026-02-23): coverage and validity gates implemented
  (`total_seeded == total_ontology_nodes`, invalid-id check), with
  unit test coverage in `tests/test_strategy_seed_all.py`.

Files:
- `scripts/setup_workspace.py`
- `scripts/strategy_seed_all.py` (new)
- `data/ontology/r36a_production_ontology_v2.5.1.json`
- `data/bootstrap/bootstrap_all.json`

Implementation notes:
- emit seed strategy for each ontology node id
- mark source as bootstrap/derived/empty

Acceptance checks:
- strategy seed coverage reaches 100% of family-descendant node ids
- no invalid ontology ids in generated strategies

### P1-02 Strategy Profiles and Inheritance

Objective:
- simplify strategy authoring while preserving advanced controls.

Status:
- DONE (2026-02-23): `profile_type` and `inherits_from` support implemented in
  `src/agent/strategy.py` with inheritance resolution for parent strategy files
  or concept-id references (latest version selection + cycle detection).
- DONE (2026-02-23): `pattern_tester.py` and `coverage_reporter.py` now load
  resolved strategies and expose profile/inheritance metadata in outputs.
- DONE (2026-02-23): `strategy_writer.py` now persists both raw and resolved
  strategy views (`*.raw.json` / `*.resolved.json`) and evaluates regression
  against resolved strategy payloads.

Files:
- `src/agent/strategy.py`
- `scripts/strategy_writer.py`
- `scripts/pattern_tester.py`

Implementation notes:
- add `profile_type` (`family_core`, `concept_standard`, `concept_advanced`)
- support parent-family defaults inherited by child strategies

Acceptance checks:
- child strategy can omit inherited fields and still evaluate correctly
- writer persists resolved and raw views

### P1-03 Materialized Feature Tables

Objective:
- avoid repeated expensive text scans.

Status:
- DONE (2026-02-23): ingestion now emits optional `section_features` and
  `clause_features` tables in both `scripts/build_corpus_index.py` and
  `scripts/build_corpus_ray.py` via `src/agent/materialized_features.py`.
- DONE (2026-02-23): `src/agent/corpus.py` now exposes feature accessors
  (`has_table`, `get_section_features`, `get_clause_features`).
- DONE (2026-02-23): `scripts/pattern_tester.py` reads `section_features`
  when present and reports feature-table usage in output.

Files:
- `scripts/build_corpus_index.py`
- `scripts/build_corpus_ray.py`
- `src/agent/corpus.py`

Implementation notes:
- add optional tables:
  - `section_features`
  - `clause_features`
- include precomputed heading/keyword/dna/parity/preemption features

Acceptance checks:
- pattern tester can read from feature tables
- runtime drops significantly vs full raw rescoring baseline

### P1-04 Template Classifier Hardening

Objective:
- produce stable template signals suitable for gating.

Status:
- DONE (2026-02-23): `scripts/template_classifier.py` now supports deterministic
  preset profiles, canonical cluster-id remapping, quality/noise diagnostics, and
  explicit quality gates (`min_clusters`, `min_non_noise_coverage`,
  `max_noise_rate`, `min_mean_confidence`) with optional `--fail-on-gate`.
- DONE (2026-02-23): detailed classifier report output added
  (`classification_report.json`) with assignment signature, cluster diagnostics,
  and gate outcomes.
- DONE (2026-02-23): `scripts/coverage_reporter.py` now supports reliable template
  cluster grouping via `--template-classifications` and `--group-by cluster_id` /
  `template_cluster`.
- Added/updated tests:
  `tests/test_template_classifier.py`, `tests/test_coverage_reporter.py`.

Files:
- `scripts/template_classifier.py`
- `scripts/coverage_reporter.py`
- `tests/test_template_classifier.py`

Implementation notes:
- enforce deterministic defaults and tuned profiles
- record cluster quality metrics and noise diagnostics

Acceptance checks:
- cluster-count and non-noise coverage gates are stable across reruns
- coverage reporter can break down by template cluster reliably

### P1-05 Structural Mapper and Fingerprint Integration

Objective:
- use structural priors for precision and outlier detection.

Status:
- DONE (2026-02-23): structural fingerprint controls are active in
  `scripts/pattern_tester.py` (`structural_fingerprint_allowlist` /
  `structural_fingerprint_blocklist`) and enforced during hit acceptance.
- DONE (2026-02-23): outlier scoring now includes peer-relative structural rarity
  signals (`heading_rarity`, `article_rarity`, `template_rarity`) with explicit
  flags in `outlier_summary` for reviewer diagnostics.
- DONE (2026-02-23): `scripts/structural_mapper.py` integrates
  `src/agent/structural_fingerprint.py` outputs, including per-template
  discrimination summaries for strategy tuning.
- Added tests:
  `tests/test_pattern_tester_gates.py` (structural rarity assertions),
  `tests/test_structural_fingerprint.py`.

Files:
- `scripts/structural_mapper.py`
- `src/agent/structural_fingerprint.py`
- `scripts/pattern_tester.py`

Implementation notes:
- integrate fingerprint allow/block strategy controls
- include structural rarity signals in outlier scoring

Acceptance checks:
- structural filters change acceptance outcomes as configured
- outlier summaries include structural rarity explanations

### P1-06 LLM Judge Tool Implementation

Objective:
- add precision audit before release-candidate strategy promotion.

Status:
- DONE (2026-02-23): added `scripts/llm_judge.py` with deterministic sampling,
  structured verdict output (`correct/partial/wrong`), precision metrics, and
  persisted report support.
- DONE (2026-02-23): `scripts/strategy_writer.py` now supports release-mode judge
  enforcement via `--release-mode`, `--judge-report`, and precision/sample gates
  (`--min-judge-precision`, `--min-judge-samples`, strict/weighted modes).
- DONE (2026-02-23): strategy save now persists versioned judge artifacts
  (`*_vNNN.judge.json`) when a judge report is provided.
- DONE (2026-02-23): dashboard API now exposes latest concept judge report at
  `/api/strategies/{concept_id}/judge/latest`.
- Added tests:
  `tests/test_llm_judge.py`, `tests/test_strategy_writer_regression.py`,
  `tests/test_tools_30k.py`.

Files:
- `scripts/llm_judge.py` (new)
- `scripts/strategy_writer.py`
- `dashboard/api/server.py`

Implementation notes:
- sample matches, judge correctness class, persist verdicts
- writer enforces judge gate when release mode is enabled

Acceptance checks:
- judge output persisted per strategy version
- release-mode save fails if precision threshold not met

### P1-07 Labeled Dataset Export Pipeline

Objective:
- provide consumable dataset outputs for downstream systems.

Status:
- DONE (2026-02-23): added `scripts/export_labeled_data.py` for evidence export
  to JSONL and Parquet with lineage metadata (`export_run_id`, `source_db`,
  `source_db_manifest`, source evidence file provenance).
- DONE (2026-02-23): export supports directory/file inputs, optional dedupe, and
  optional inclusion of NOT_FOUND rows.
- Added tests:
  `tests/test_export_labeled_data.py`, `tests/test_tools_30k.py`.

Files:
- `scripts/export_labeled_data.py` (new)
- `scripts/evidence_collector.py`

Implementation notes:
- export JSONL and Parquet
- include lineage fields (run_id, strategy_version, source_db)

Acceptance checks:
- export runs on pilot and full snapshots
- schema is documented and versioned

## P2: Swarm and Full Rollout Operations

### P2-01 Swarm Script Implementation

Objective:
- deliver planned tmux-based multi-agent control scripts.

Status:
- DONE (2026-02-23): implemented tmux swarm control scripts:
  `swarm/launch.sh`, `swarm/start-agent.sh`, `swarm/send-to-agent.sh`,
  `swarm/broadcast.sh`, `swarm/status.sh`, `swarm/kill.sh`,
  `swarm/dispatch-wave.sh`, plus shared helpers in `swarm/common.sh`.
- DONE (2026-02-23): added `swarm/swarm.conf` assignment registry with wave/pane/backend
  mapping and concept whitelist column.
- DONE (2026-02-23): added prompt composition assets:
  `swarm/prompts/family_agent_base.md`, `swarm/prompts/common-rules.md`,
  `swarm/prompts/platform-conventions.md`, `swarm/prompts/indebtedness.md`,
  `swarm/prompts/enrichment/indebtedness.md`.
- Validation:
  - `bash -n swarm/*.sh`
  - `./swarm/dispatch-wave.sh 1 --dry-run --session test-agent-swarm`

Files:
- `swarm/launch.sh` (new)
- `swarm/start-agent.sh` (new)
- `swarm/send-to-agent.sh` (new)
- `swarm/broadcast.sh` (new)
- `swarm/status.sh` (new)
- `swarm/kill.sh` (new)
- `swarm/dispatch-wave.sh` (new)
- `swarm/swarm.conf` (new)

Acceptance checks:
- end-to-end wave dispatch works from CLI
- status output shows per-family progress

### P2-02 Family Checkpoint Protocol

Objective:
- resume safely after interruption without losing strategy/evidence state.

Status:
- DONE (2026-02-23): `swarm/start-agent.sh` now initializes and updates
  `workspaces/<family>/checkpoint.json` on launch, appends checkpoint-derived
  resume context into the assembled family prompt, and records session/pane start metadata.
- DONE (2026-02-23): `swarm/dispatch-wave.sh` now uses checkpoint status for
  resume-aware dispatch filtering (`--failed-only`, completed-skip defaults,
  `--force-restart`, `--no-resume`) and emits resume summaries in dry-run output.
- DONE (2026-02-23): `swarm/status.sh` now surfaces checkpoint status per family.

Files:
- `swarm/start-agent.sh`
- `swarm/dispatch-wave.sh`
- `workspaces/*/checkpoint.json` (runtime artifact)

Acceptance checks:
- interrupted run resumes from checkpointed concept and iteration

### P2-03 Concept Whitelist Enforcement

Objective:
- prevent cross-family contamination.

Status:
- DONE (2026-02-23): `swarm/swarm.conf` whitelist column is exported by
  `swarm/start-agent.sh` via `AGENT_CONCEPT_WHITELIST`.
- DONE (2026-02-23): `scripts/strategy_writer.py` now enforces concept whitelist
  gating (CLI or `AGENT_CONCEPT_WHITELIST`), rejects out-of-scope saves, and logs
  reroute records to `workspaces/<family>/out_of_scope_discoveries.jsonl` (or custom path).
- Added tests:
  `tests/test_strategy_writer_whitelist.py`.

Files:
- `swarm/swarm.conf`
- `swarm/prompts/family_agent_base.md` (new)
- `scripts/strategy_writer.py`

Acceptance checks:
- out-of-scope concepts are rejected or rerouted
- out-of-scope discoveries are logged separately

### P2-04 Wave Scheduler and Family Queue

Objective:
- coordinate 49-family rollout with deterministic sequencing.

Status:
- DONE (2026-02-23): added `scripts/wave_scheduler.py` for dependency-aware queue
  planning across waves (`--mode ready|failed|all`, checkpoint-state aware,
  dependency blocker reporting, optional families-out artifact).
- DONE (2026-02-23): `swarm/dispatch-wave.sh` now supports failed-family reruns
  (`--failed-only`) and dependency-aware skip behavior using optional
  `depends_on` entries in `swarm.conf`.
- Added tests:
  `tests/test_wave_scheduler.py`.

Files:
- `swarm/dispatch-wave.sh`
- `scripts/wave_scheduler.py` (new)

Acceptance checks:
- queue supports dependency-aware wave transitions
- reruns can target failed families only

### P2-05 Dashboard Operational Views

Objective:
- expose strategy/evidence/quality status for human review.

Status:
- DONE (2026-02-23): added backend review endpoints in
  `dashboard/api/server.py` for:
  - strategy timeline: `/api/review/strategy-timeline/{concept_id}`
  - evidence browser feed: `/api/review/evidence`
  - coverage heatmap matrix: `/api/review/coverage-heatmap`
  - judge history: `/api/review/judge/{concept_id}/history`
  - agent activity from checkpoints: `/api/review/agent-activity`
- DONE (2026-02-23): wired dedicated frontend views in
  `dashboard/src/app/review/*`, plus review home routing
  (`dashboard/src/app/review/page.tsx`) and sidebar navigation.
- DONE (2026-02-23): completed evidence workflow polish with pagination/reset controls,
  and timeline/judge concept-id autocomplete from strategy registry.
- Added tests:
  `tests/test_dashboard_review_ops.py`.

Files:
- `dashboard/src/app/*`
- `dashboard/src/lib/*`
- `dashboard/api/server.py`

Acceptance checks:
- view availability: strategy timeline, evidence browser, coverage heatmap, judge review, agent activity

### P2-06 Full-Corpus Orchestration Runbook

Objective:
- standardize full-corpus production runs and teardown (current baseline: 12,583 docs).

Status:
- DONE (2026-02-23): added `plans/full_runbook.md` with end-to-end production
  workflow covering Ray bring-up, corpus build/validation, template gates,
  pilot strategy/evidence flow, labeled export, swarm dispatch, and teardown.

Files:
- `ray-cluster.yaml`
- `scripts/build_corpus_ray.py`
- `plans/full_runbook.md` (new)

Acceptance checks:
- runbook reproducibly executes full run with manifest and artifacts

### P2-07 Release and Lineage Checklist

Objective:
- ensure dataset publication is reproducible and auditable.

Status:
- DONE (2026-02-23): added `plans/release_checklist.md` with build integrity,
  strategy quality gates, swarm governance checks, lineage requirements, and
  release-bundle sign-off checklist.

Files:
- `plans/release_checklist.md` (new)
- `scripts/export_labeled_data.py`

Acceptance checks:
- each release includes lineage manifest and quality summary

## P3: Gate-5 Rollout Automation

### P3-01 Family-Scale Whitelist Patterns

Objective:
- make concept-whitelist enforcement practical for full family subtrees.

Status:
- DONE (2026-02-23): `scripts/strategy_writer.py` now supports subtree wildcard
  entries in concept whitelists (e.g., `debt_capacity.indebtedness.*`) in
  addition to exact IDs.
- DONE (2026-02-23): whitelist gate diagnostics now distinguish
  exact vs prefix entries and persist prefix metadata in save payload.
- Added tests:
  `tests/test_strategy_writer_whitelist.py`.

Files:
- `scripts/strategy_writer.py`
- `tests/test_strategy_writer_whitelist.py`

Acceptance checks:
- family-level wildcard whitelist allows child concept saves in-scope
- out-of-scope concepts still rejected and logged

### P3-02 Full-Family Workspace Bootstrap Automation

Objective:
- initialize all 49 family workspaces deterministically from ontology + bootstrap.

Status:
- DONE (2026-02-23): added `scripts/setup_workspaces_all.py` for batch family
  setup orchestration with dry-run planning, skip-existing controls, summary output,
  and fail-fast behavior.
- DONE (2026-02-23): `scripts/setup_workspace.py` now supports exact
  `--family-id` targeting for deterministic family subtree extraction.
- Added tests:
  `tests/test_setup_workspaces_all.py`, `tests/test_setup_workspace.py`.

Files:
- `scripts/setup_workspaces_all.py` (new)
- `scripts/setup_workspace.py`
- `tests/test_setup_workspaces_all.py`
- `tests/test_setup_workspace.py`

Acceptance checks:
- batch setup processes full ontology family list
- reruns skip existing workspaces unless explicitly forced

### P3-03 Ontology-Driven Swarm Assignment Generation

Objective:
- generate consistent 49-family swarm assignments with wave distribution and
  subtree whitelist defaults.

Status:
- DONE (2026-02-23): added `scripts/generate_swarm_conf.py` to create
  assignment files from ontology with:
  - wave allocation (`wave1`, `wave2` anchors, `wave3`, optional `wave4`)
  - pane round-robin scheduling
  - subtree whitelist entries (`family_id,family_id.*`)
  - optional dependency map injection
- DONE (2026-02-23): generated full assignment candidate:
  `swarm/swarm.full49.conf` (49 assignments).
- Added tests:
  `tests/test_generate_swarm_conf.py`.

Files:
- `scripts/generate_swarm_conf.py` (new)
- `swarm/swarm.full49.conf` (generated)
- `tests/test_generate_swarm_conf.py`

Acceptance checks:
- generated config covers all ontology families
- wave/pane distribution is deterministic and validated

### P3-04 Swarm Run Ledger and Gate Snapshot Artifacts

Objective:
- produce deterministic run-state artifacts for Gate-4/5 transition review.

Status:
- DONE (2026-02-23): added `scripts/swarm_run_ledger.py` to emit
  machine-readable swarm ledger snapshots (assignment/checkpoint/workspace state)
  with stale-running detection and optional JSONL append mode.
- DONE (2026-02-23): generated active Wave-1 ledger artifact on the 12,583-doc
  corpus baseline:
  `plans/wave1_swarm_ledger_2026-02-23.json`.
- Added tests:
  `tests/test_swarm_run_ledger.py`, `tests/test_tools_30k.py`.

Files:
- `scripts/swarm_run_ledger.py` (new)
- `tests/test_swarm_run_ledger.py` (new)
- `tests/test_tools_30k.py`

Acceptance checks:
- ledger snapshot includes all in-scope families with status counts
- stale-running families are explicitly identified for operator action
- artifact can be appended to longitudinal JSONL history

### P3-05 Checkpoint Auto-Progression Hooks

Objective:
- keep checkpoint state synchronized with strategy/evidence persistence events.

Status:
- DONE (2026-02-23): `scripts/strategy_writer.py` now updates
  `workspaces/<family>/checkpoint.json` after successful strategy save
  (`iteration_count`, `last_strategy_version`, `current_concept_id`,
  `last_saved_strategy_file`, `last_update`).
- DONE (2026-02-23): `scripts/evidence_collector.py` now updates checkpoint
  evidence metadata (`last_evidence_file`, `last_evidence_run_id`,
  `last_evidence_records`, `last_update`) and keeps status aligned.
- Added tests:
  `tests/test_strategy_writer_views.py`, `tests/test_evidence_collector.py`.

Files:
- `scripts/strategy_writer.py`
- `scripts/evidence_collector.py`
- `tests/test_strategy_writer_views.py`
- `tests/test_evidence_collector.py`

Acceptance checks:
- successful strategy saves increment checkpoint iteration/version fields
- successful evidence writes record last evidence metadata in checkpoint
- `swarm_run_ledger.py` reflects updated checkpoint progression without manual edits

### P3-06 Wave Transition Gate Enforcement

Objective:
- prevent premature Wave-2/3 dispatch when prerequisite waves are not complete.

Status:
- DONE (2026-02-23): added `scripts/wave_transition_gate.py` with
  completion-status evaluation, waiver support, and machine-readable go/no-go output.
- DONE (2026-02-23): `swarm/dispatch-wave.sh` now enforces transition gate by
  default for `wave > 1` with support for:
  - `--waiver-file`
  - `--transition-scope previous|all-prior`
  - `--completed-statuses`
  - `--transition-artifact`
  - `--skip-transition-gate` (manual override)
- Added tests:
  `tests/test_wave_transition_gate.py`, `tests/test_tools_30k.py`.

Files:
- `scripts/wave_transition_gate.py` (new)
- `swarm/dispatch-wave.sh`
- `tests/test_wave_transition_gate.py` (new)
- `tests/test_tools_30k.py`

Acceptance checks:
- wave transition check returns non-zero when prerequisite families are incomplete
- waiver file can explicitly unblock selected prerequisite families
- dispatch-wave blocks wave>1 launch when transition gate fails

### P3-07 Swarm Watchdog and Alert Artifacts

Objective:
- reduce manual pane supervision by emitting actionable stale/orphan alerts.

Status:
- DONE (2026-02-23): added `scripts/swarm_watchdog.py` to detect:
  - stale running checkpoints (`last_update` age threshold),
  - bootstrap-stuck families (running with no strategy/evidence beyond grace window),
  - optional orphaned running families via tmux pane activity checks.
- DONE (2026-02-23): watchdog supports:
  - severity-based failure policy (`--fail-on`)
  - optional checkpoint mutation to `stalled` (`--mark-stalled`, `--mark-on`)
  - JSON + JSONL artifact outputs for trend monitoring.
- Added tests:
  `tests/test_swarm_watchdog.py`, `tests/test_tools_30k.py`.

Files:
- `scripts/swarm_watchdog.py` (new)
- `tests/test_swarm_watchdog.py` (new)
- `tests/test_tools_30k.py`
- `plans/full_runbook.md`
- `plans/release_checklist.md`

Acceptance checks:
- watchdog returns structured alerts for stale/bootstrapping issues
- critical alert policy can fail CI/automation checks
- optional `mark-stalled` path updates checkpoint status deterministically

### P3-08 Family Artifact Manifest Pipeline

Objective:
- emit deterministic per-family strategy/evidence/judge manifests for gate reviews.

Status:
- DONE (2026-02-23): added `scripts/swarm_artifact_manifest.py` to produce
  assignment-scoped artifact manifests with:
  - checkpoint progression metadata
  - strategy version/raw/resolved counts
  - evidence file + record counts
  - judge report counts
  - review-ready state classification per family.
- Added tests:
  `tests/test_swarm_artifact_manifest.py`, `tests/test_tools_30k.py`.

Files:
- `scripts/swarm_artifact_manifest.py` (new)
- `tests/test_swarm_artifact_manifest.py` (new)
- `tests/test_tools_30k.py`
- `plans/full_runbook.md`
- `plans/release_checklist.md`

Acceptance checks:
- manifest includes all in-scope families for requested wave/filter
- summary includes strategy/evidence/judge totals and review-ready counts
- output is appendable to JSONL longitudinal history

### P3-09 Consolidated Ops Snapshot Gate

Objective:
- provide one command for periodic swarm health + transition go/no-go snapshots.

Status:
- DONE (2026-02-23): added `scripts/swarm_ops_snapshot.py` to orchestrate:
  - `swarm_run_ledger.py`
  - `swarm_watchdog.py`
  - `swarm_artifact_manifest.py`
  - optional `wave_transition_gate.py` for next-wave checks
- DONE (2026-02-23): supports consolidated pass/fail policies:
  - `--require-no-critical-alerts`
  - `--require-next-wave-allowed`
  with JSON/JSONL output for timeline tracking.
- Added tests:
  `tests/test_swarm_ops_snapshot.py`, `tests/test_tools_30k.py`.

Files:
- `scripts/swarm_ops_snapshot.py` (new)
- `tests/test_swarm_ops_snapshot.py` (new)
- `tests/test_tools_30k.py`
- `plans/full_runbook.md`
- `plans/release_checklist.md`

Acceptance checks:
- snapshot emits merged summary for ledger/watchdog/manifest/transition
- required-gate flags return non-zero when controls are not met
- output can be consumed as single go/no-go artifact per run interval

### P3-10 Wave Lifecycle Promotion Protocol

Objective:
- deterministically promote wave checkpoints from `running` to `completed/locked`
  when artifact criteria are met, so transition gates reflect actual progress.

Status:
- DONE (2026-02-23): added `scripts/wave_promote_status.py` to promote
  checkpoint statuses by wave with configurable criteria:
  - source/target statuses (`--from-statuses`, `--to-status`)
  - required strategy/evidence artifact thresholds
  - dry-run and fail-on-blocked controls
  - JSON artifact output for auditability
- DONE (2026-02-23): Wave-1 promotion applied via
  `plans/wave1_status_promotion_2026-02-23.json`:
  - promoted: 5/5 families
  - result: Wave-2 transition gate unblocked (`blocked=0`)
- Added tests:
  `tests/test_wave_promote_status.py`, `tests/test_tools_30k.py`.

Files:
- `scripts/wave_promote_status.py` (new)
- `tests/test_wave_promote_status.py` (new)
- `tests/test_tools_30k.py`
- `plans/full_runbook.md`
- `plans/release_checklist.md`

Acceptance checks:
- promotion only applies to families meeting configured artifact criteria
- dry-run reports candidate promotions without mutation
- transition gate changes from blocked to allowed when prerequisites are promoted

### P3-11 Queue-Safe Multi-Family Dispatch

Objective:
- prevent pane clobbering when a wave contains multiple families mapped to the
  same pane (e.g., Wave-3 in `swarm.full49.conf`).

Status:
- DONE (2026-02-23): `swarm/dispatch-wave.sh` now supports queue-safe launch
  controls:
  - `--max-starts-per-pane` (default `1`) to cap starts per pane per invocation
  - skip `status=running` families unless `--force-restart` is used
  - pane-busy guard: if a pane already has a running family, additional families
    assigned to that pane are skipped for that dispatch cycle
- Verified behavior on Wave-3:
  - first dispatch starts 4 families (one per pane)
  - immediate subsequent dispatch attempts correctly report no eligible starts
    while panes are busy with running families.

Files:
- `swarm/dispatch-wave.sh`
- `plans/wave3_dispatch_dry_run_queue_safe_2026-02-23.txt`
- `plans/wave3_dispatch_live_2026-02-23.txt`
- `plans/wave3_dispatch_dry_run_poststart_2026-02-23.txt`

Acceptance checks:
- no dispatch invocation starts more than configured per-pane limit
- running family checkpoints are not restarted by default
- multi-family waves advance by repeated dispatch cycles without pane overwrite

## Suggested Execution Order

1. P0-01, P0-02
2. P0-03, P0-04, P0-05
3. P0-06, P0-07, P0-08
4. P1-01, P1-02, P1-03
5. P1-04, P1-05, P1-06, P1-07
6. P2-01, P2-02, P2-03, P2-04
7. P2-05, P2-06, P2-07
8. P3-01, P3-02, P3-03, P3-04, P3-05, P3-06, P3-07, P3-08, P3-09, P3-10, P3-11
