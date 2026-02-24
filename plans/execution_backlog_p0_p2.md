# Agent Execution Backlog (P0/P1/P2) - Legacy Snapshot

Authoritative execution docs:
- `plans/master_rollout_plan.md`
- `plans/master_execution_backlog_p0_p2.md`

This file is retained as historical context for earlier P0/P1/P2 decisions.

## Scope

This backlog converts the current review into an execution plan with concrete deliverables,
acceptance checks, and sequencing for the `Agent/` repository.

Status legend:
- `DONE` = implemented in code
- `NEXT` = immediate queue
- `LATER` = post-MVP hardening

---

## P0 (Stability + Correctness)

### P0.1 Regression gate must evaluate real corpus text (`DONE`)
- Problem: `strategy_writer.py` regression checks were reading metadata rows, not clause/section text.
- Deliverable: Use aggregated `section_text` per doc when available; fallback to document text column only if needed.
- Files:
  - `scripts/strategy_writer.py`
- Acceptance:
  - `python3 scripts/strategy_writer.py ... --db corpus_index/corpus.duckdb` evaluates real matches.
  - Synthetic smoke test on in-memory DuckDB shows different hit rates by template group.

### P0.2 Content-addressed `doc_id` (`DONE`)
- Problem: `doc_id` was based on filename + file size, unstable across path/packaging changes.
- Deliverable: Compute `doc_id` as SHA-256 of normalized text (truncated to 16 hex chars for compatibility).
- Files:
  - `scripts/build_corpus_index.py`
- Acceptance:
  - Same document content produces the same `doc_id` across different file names/locations.

### P0.3 Enforce schema version checks in all CLI entrypoints (`DONE`)
- Problem: MVP requires schema checks; tools currently do not fail fast on version mismatch.
- Deliverable:
  - Add shared helper to assert `CorpusIndex.schema_version == SCHEMA_VERSION`.
  - Apply helper in all scripts that open `corpus.duckdb`.
- Files:
  - `src/agent/corpus.py`
  - `scripts/*.py` using `CorpusIndex`/DuckDB
- Acceptance:
  - Version mismatch exits non-zero with clear error message.

### P0.4 Restore missing MVP scripts (`DONE`)
- Problem: `sync_corpus.py` and `dna_discoverer.py` are in MVP plan but missing from repo.
- Deliverable:
  - Add `scripts/sync_corpus.py` (staged sync semantics).
  - Add `scripts/dna_discoverer.py` (TF-IDF + log-odds outputs).
- Files:
  - `scripts/sync_corpus.py` (new)
  - `scripts/dna_discoverer.py` (new)
- Acceptance:
  - Both tools run with `--help`.
  - Integration smoke test passes on fixture corpus.

### P0.5 Close test gaps called out in MVP (`DONE`)
- Problem: No tests for `corpus.py` and `dna.py` despite MVP verification requirements.
- Deliverable:
  - Add `tests/test_corpus.py`.
  - Add `tests/test_dna.py`.
  - Add targeted script-level regression test for `strategy_writer` text-source behavior.
- Files:
  - `tests/test_corpus.py` (new)
  - `tests/test_dna.py` (new)
  - `tests/test_strategy_writer_regression.py` (new)
- Acceptance:
  - `pytest -q` passes with new tests.

### P0.6 Plan coherence pass (`NEXT`)
- Problem: execution governance must move to a single authoritative gate ladder.
- Deliverable:
  - Adopt `master_rollout_plan.md` as the controlling roadmap.
  - Align backlog execution against `master_execution_backlog_p0_p2.md`.
  - Treat `final_target_vision.md` and other plan docs as supporting references.
- Files:
  - `plans/master_rollout_plan.md`
  - `plans/master_execution_backlog_p0_p2.md`
  - `plans/final_target_vision.md`
- Acceptance:
  - No contradictory active gate definitions remain across execution docs.

---

## P1 (MVP Completion + Quality Hardening)

### P1.1 Metadata extraction implementation
- Deliverable: implement `src/agent/metadata.py` and wire into ingestion.
- Acceptance: borrower/admin agent/facility/date fields populated for benchmark sample.

### P1.2 Strategy schema alignment
- Deliverable: align runtime `Strategy` shape with final target (including template override structure).
- Acceptance: round-trip compatibility and migration of existing strategy files.

### P1.3 Template-aware evaluation
- Deliverable: implement `template_classifier.py` + integrate with `coverage_reporter.py`.
- Acceptance: coverage reported by template cluster on 500-doc gate.

### P1.4 Structural mapper
- Deliverable: implement `structural_mapper.py` for article/section position priors.
- Acceptance: outputs stable distributions and typical positions for pilot family.

### P1.5 Evidence contract hardening
- Deliverable: introduce explicit `NOT_FOUND` proof object with search coverage and near misses.
- Acceptance: evidence files include positive and absence records with provenance.

---

## P2 (Scale + Orchestration Sophistication)

### P2.1 Swarm reliability primitives
- Deliverable: checkpoint files, agent concept whitelist, restart-safe workflows.
- Acceptance: interrupted run resumes without strategy/evidence loss.

### P2.2 Failure routing and gate orchestration
- Deliverable: route failures by type (retrieval/definition/xref/quality gate) with actionable diagnostics.
- Acceptance: failed runs produce deterministic route-to-fix plans.

### P2.3 Dashboard integration
- Deliverable: Streamlit views for strategy evolution, evidence browser, coverage heatmap, and review overrides.
- Acceptance: pilot run artifacts are explorable end-to-end in dashboard.

### P2.4 Dataset lineage + immutable snapshots
- Deliverable: versioned index snapshots, migration ledger, and reproducible run metadata.
- Acceptance: any strategy/evidence output can be traced to exact corpus/index version.

---

## Execution Order

Execution order is now maintained in:
- `plans/master_execution_backlog_p0_p2.md`
