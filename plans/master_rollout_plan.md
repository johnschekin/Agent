# Master Rollout Plan: Ontology-to-Clause Linking

## Purpose

This document is the single source of truth for scaling Agent from the indebtedness pilot
into full ontology coverage (3,500+ nodes across 49 families).

It unifies roadmap, sequencing, and quality gates from:
- `plans/final_target_vision.md`
- `plans/execution_backlog_p0_p2.md`
- `plans/repurpose_targets_p0_p2_checklist.md`
- `plans/pilot_protocol.md`
- `~/.claude/plans/snuggly-meandering-lagoon.md`

## Plan Governance

1. This file is authoritative for execution order and gates.
2. Supporting plans remain useful references but cannot override this plan.
3. Any gate or milestone change must be updated here first.

## Current Baseline (as of 2026-02-23)

- Ontology footprint:
  - 6 domains
  - 49 families
  - 3,532 family-descendant nodes (3,684 ids including non-family/domain-level ids)
- Strategy baseline:
  - Bootstrap strategies: 344 concepts
  - Bootstrap overlap with family-descendant ontology nodes: 344/3,532 (~9.74%)
- Workspace baseline:
  - Workspace directories materialized: 49/49 families
  - Seed status: 48 newly bootstrapped + 1 pre-existing (`indebtedness`)
- Orchestration baseline:
  - Wave-1 calibration families: 5 (`available_amount`, `dividend_blockers`, `carve_outs`, `cross_covenant`, `dispositions`)
  - Wave-1 checkpoints: 5/5 present, all `completed`
  - Wave-1 current artifacts: `with_strategy=5/5`, `with_evidence=5/5`, `review_ready=5/5`
  - Wave-1 watchdog alerts: `critical=0`, `warning=0`
  - Wave-2 transition: open (`blocked=0`) with ready families `inv`, `rp`, `indebtedness`, `liens`
  - Wave-2 dispatch: executed (`inv`, `rp`, `indebtedness`, `liens`), checkpoints now `completed`
  - Wave-2 current artifacts: `with_strategy=4/4`, `with_evidence=4/4`, `review_ready=4/4`
  - Wave-3 transition: open (`blocked=0`) with ready queue size `40` (dry-run dispatch validated)
  - Wave-3 dispatch: queue-safe batch cadence active
    - batch-1 promoted (`acquisition_debt`, `affiliate_txns`, `amendments_voting`, `accounting`)
    - batch-2 promoted (`collateral`, `builders`, `contribution_debt`, `assignments`)
    - batch-3 launched (`ebitda`, `corporate_structure`, `events_of_default`, `change_of_control`)
  - Wave-3 current artifacts: `completed=8`, `running=4`, `with_evidence=8`, `critical_alerts=0`, `warning_alerts=0`
- Corpus baseline in repo local index (`corpus_index/corpus.duckdb`):
  - 12,583 documents
  - 12,583 cohort documents
  - Cohort parse success: sections 99.25%, clauses 99.17%, definitions 99.95%
- Known constraints:
  - Full-family swarm assignment exists (`swarm/swarm.full49.conf`) but is not yet active default
  - Full 49-family wave execution and release sign-off have not yet been run end-to-end

## Target Operating Model

### Retrieval Architecture

Use a two-stage retrieval architecture for scale:

1. Stage A: Family localization
- Locate candidate sections for each family using heading/keyword/DNA/structure signals.
- Materialize family candidate sets.

2. Stage B: Concept localization
- Evaluate child/grandchild strategies only within candidate sets.
- Run clause-level scoring plus precision gates.

This avoids full-corpus rescoring per concept and is required for 3,500-node throughput.

### Strategy Model

Use strategy profiles to reduce complexity while retaining advanced controls:

- `family_core`
  - heading patterns
  - keyword anchors
  - article/section priors
  - outlier policy
- `concept_standard`
  - family_core + concept-specific keywords + definition dependencies
- `concept_advanced`
  - concept_standard + parity/preemption/fingerprint/template-module constraints

All advanced fields must remain optional and default-permissive.

### Quality Model

Do not rely on global hit rate alone.

Required quality dimensions:
- precision (gold set + judge sample)
- recall coverage (concept and family)
- template stability (no major blind spots)
- outlier risk distribution
- did-not-find quality (structured absence proof)

## Unified Gate Ladder

### Gate 0: Plan Control Gate

Objective:
- enforce one execution plan and remove contradictory gate definitions.

Deliverables:
- this master plan
- ticketized backlog aligned to this plan
- legacy backlog linked to master

Exit criteria:
- no stale references to non-authoritative plans in active execution docs
- all new work item discussions reference this file

### Gate 1: Foundation and Corpus Gate

Objective:
- stabilize ingestion and core evaluation contracts.

Scope:
- schema/version enforcement
- deterministic ids and run manifests
- ingestion performance and backpressure
- evidence schema v2 foundation

Exit criteria:
- successful 500 and 5K gated runs with artifacts
- reproducible run manifest for each corpus build
- Ray writer finalization no longer dominates wall-clock completion
- all core tests passing

Primary artifacts:
- `corpus_<run_id>.duckdb`
- `run_manifest.json`
- `corpus_profile.json`
- parser anomaly reports

### Gate 2: Pilot Coverage Gate (Indebtedness)

Objective:
- finish one family end-to-end at clause-level quality.

Scope:
- family-level strategy refinement
- at least five child concepts to working state
- evidence persistence and strategy versioning

Exit criteria:
- family hit rate > 80%
- at least five L2 child concepts > 50% hit rate
- gold-set precision > 75%
- all evidence rows include valid `ontology_node_id`
- no unresolved parser blind spot for major template clusters

Primary artifacts:
- strategy version history
- evidence files
- pilot result bundle (metrics, misses, outliers, not-found)

### Gate 3: Quality Hardening Gate

Objective:
- standardize precision controls before broad family rollout.

Scope:
- definition type gates
- scope parity and preemption gates
- unified confidence runtime enforcement
- template-aware quality gates
- judge-assisted precision workflow

Exit criteria:
- measurable precision lift from P0 gates on pilot benchmark
- proviso/preemption error bucket reduced materially
- strategy save path enforces confidence and outlier policies
- judge workflow implemented for release-candidate strategies

Primary artifacts:
- calibrated policy configs
- gate diagnostics
- precision delta reports

### Gate 4: Orchestration Gate

Objective:
- make multi-family execution reliable and restart-safe.

Scope:
- swarm scripts (launch/start/send/status/dispatch/kill)
- checkpoint protocol per family
- concept whitelist enforcement
- family wave scheduling

Exit criteria:
- wave runs across multiple families with deterministic restart/resume
- each run produces strategy/evidence manifests and status ledger
- no manual pane-level supervision required for routine wave progress

Primary artifacts:
- swarm run ledger
- per-family checkpoint files
- wave summaries

### Gate 5: Full Rollout Gate (All Families)

Objective:
- complete ontology linking coverage at production scale.

Scope:
- full-corpus runs on the canonical corpus snapshot (currently 12,583 docs),
  with refresh reruns as new filings are added
- all families and their subtree concepts
- exportable labeled dataset

Exit criteria:
- all 49 families processed through standard workflow
- coverage/precision thresholds met or explicitly waived with rationale
- lineage-complete dataset snapshot published

Primary artifacts:
- full labeled dataset (JSONL + Parquet)
- lineage manifest
- release report

## Family Rollout Strategy

Use complexity-aware wave sequencing:

- Wave 1 (calibration families): 3-5 medium families
- Wave 2 (high-volume families): indebtedness, liens, RP, investments
- Wave 3 (remaining families)
- Wave 4 (long-tail cleanup and relabel)

For each family, enforce the same lifecycle:
- seed -> test -> refine -> evidence -> strategy save -> review -> lock

## Metrics Contract

Track and publish these per run:
- retrieval:
  - docs tested
  - docs with sections/clauses/definitions
  - candidate set sizes (family and concept)
- quality:
  - hit_rate
  - precision_estimate
  - outlier_rate / high_risk_rate / review_rate
  - template-group hit rates and spread
- operations:
  - runtime by stage
  - queue depth/backlog signals
  - restart count

## Risk Register

1. Parser blind spots in specific templates
- Mitigation: anomaly queue + fallback parse path + rerun policy

2. Strategy overfitting to one template family
- Mitigation: template stability gate and per-template acceptance

3. Scaling cost from repeated full scans
- Mitigation: two-stage retrieval and materialized feature tables

4. Orchestration fragility under long runs
- Mitigation: checkpoints, whitelists, and wave-level health checks

## Change Control

Before moving to the next gate, publish:
- gate checklist status
- metrics summary
- unresolved risks and owner
- go/no-go decision
