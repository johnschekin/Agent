# Agent Wave 3 Readiness Plan (Execution Version)

Owner: Agent coding agent (implementation)
Oversight: Neutron integration lead (this plan)
Status: Active
Last Updated: 2026-02-27

## 1. Mission
Make `Projects/Agent` implementation-ready for Neutron Wave 3 by closing all contract, determinism, lineage, governance, and handoff gaps.

This document is the execution source of truth. Implement exactly in the PR sequence below unless an explicit blocker requires reorder.

## 2. Non-Negotiable Exit Criteria
All must be true:

- Deterministic parser/linker outputs for fixed inputs and config.
- Canonical IDs stable and validated: `document_id`, `section_reference_key`, `clause_key`, `ontology_node_id`, `chunk_id`.
- Bulk linking applies calibration in runtime, not only storage.
- Evidence rows include full anchor + lineage fields required for Wave 3 handoff.
- No placeholder runtime versions (`bulk_linker_v1`, `worker_v1`, `1.0`) in persisted run/link/evidence writes.
- Alias resolution is ontology-version scoped and cycle-safe.
- Export contracts provide strict, versioned Wave 3 payloads.
- Admin write endpoints are auditable and hardened against default-token misuse.
- P0/P1 red-team findings closed and covered by regression tests.

## 3. Current Verified Gaps (From Deep Dive)

- Hardcoded lineage versions in runtime writes:
  - `scripts/bulk_family_linker.py:1084`
  - `scripts/bulk_family_linker.py:1086`
  - `scripts/link_worker.py:625`
  - `scripts/link_worker.py:627`
- Calibration dead path in bulk linking runtime:
  - `scripts/bulk_family_linker.py:1132`
- Alias table lacks ontology-version scoping:
  - `src/agent/link_store.py:160`
  - resolver at `src/agent/link_store.py:1304`
- Evidence schema not Wave 3-complete:
  - DDL at `src/agent/link_store.py:231`
  - persistence at `src/agent/link_store.py:2161`
- Export contracts still legacy:
  - `scripts/evidence_collector.py:255` (`evidence_v2`)
  - `scripts/export_labeled_data.py:298` (`labeled_export_v1`)
- Admin tokens allow default local token path and minimal audit context:
  - `dashboard/api/server.py:499`
  - `dashboard/api/server.py:561`
  - `dashboard/api/server.py:608`
  - `dashboard/api/server.py:8912`
- Conflict matrix likely ineffective with current ontology shape (edge/node adapter mismatch):
  - `scripts/bulk_family_linker.py:1478`
  - `src/agent/conflict_matrix.py:85`

## 4. Canonical Decisions (Locked)

### 4.1 IDs
- `document_id`: existing content-addressed `doc_id` in corpus index.
- `section_reference_key`: `"{document_id}:{section_number}"` until canonical semantic section names are available in Agent parser output.
- `clause_key`: existing normalized clause identity (`clause_key`, fallback `clause_id`, else `__section__`).
- `ontology_node_id`: explicit ontology node id validated against loaded ontology for a specific ontology version.
- `chunk_id`: `sha256("{document_id}|{section_reference_key}|{clause_key}|{char_start}|{char_end}|{text_hash}")`.

### 4.2 Policy Decision
Persist `policy_decision` in `{must, review, reject}` and `policy_reasons: list[str]`.

Baseline rules:
- `must`: calibrated score >= high threshold and not conflict-blocked.
- `review`: calibrated score >= medium threshold but < high, or uncertainty/conflict warning.
- `reject`: below medium threshold or contract validation failure.

### 4.3 Versioning
Persist for every run/link/evidence/export row where applicable:
- `run_id`
- `corpus_version`
- `parser_version`
- `ontology_version`
- `ruleset_version`
- `git_sha` (best-effort)
- `created_at` UTC

No placeholder version literals allowed in write paths.

## 5. PR Sequence (Required Order)

## PR-1: Ontology Contract Adapter + Conflict Matrix Fix

### Goal
Make ontology ingestion and conflict policy computation correct for actual ontology JSON shape.

### Implementation
- Add `src/agent/ontology_contract.py`:
  - flatten nodes from `domains[].children...`
  - expose `node_by_id`, `family_by_node_id`, `ontology_version` from `metadata.version`
  - normalize edges (`source_id`/`target_id`)
- Update `src/agent/conflict_matrix.py`:
  - support `source_id`/`target_id`
  - resolve families via flattened node map
- Update `scripts/bulk_family_linker.py`:
  - use adapter to build matrix
  - strict mode: if ontology loaded and edges present but matrix empty, emit warning/fail flag

### Files
- `src/agent/ontology_contract.py` (new)
- `src/agent/conflict_matrix.py`
- `scripts/bulk_family_linker.py`
- tests

### Tests
- add/update:
  - `tests/test_ontology_contract.py` (new)
  - `tests/test_conflict_matrix.py` (new or expanded)
  - `tests/test_bulk_family_linker.py` conflict matrix integration case

### Acceptance
- Non-zero policy matrix generated on `data/ontology/r36a_production_ontology_v2.5.1.json`.
- `ontology_version` extracted from ontology metadata and available to callers.

---

## PR-2: LinkStore Schema v1.3 + Migrations

### Goal
Add missing lineage/contract fields and ontology-version-aware aliasing.

### Implementation
- Bump `SCHEMA_VERSION` in `src/agent/link_store.py`.
- Extend tables:
  - `family_scope_aliases`: add `ontology_version`.
  - `family_links`: add `ontology_version`, `score_raw`, `score_calibrated`, `policy_decision`, `policy_reasons`.
  - `link_evidence`: add `run_id`, `doc_id`, `section_number`, `section_reference_key`, `clause_key`, `chunk_id`, `corpus_version`, `parser_version`, `ontology_version`.
  - `family_link_runs`: add `ontology_version`, `ruleset_version`, `git_sha`.
- Add migration helpers in `_create_schema()` with backfill defaults and idempotency.
- Update read/write methods:
  - `upsert_family_alias`, `get_canonical_scope_id`, `resolve_scope_aliases`
  - `create_links`, `save_evidence`, `create_run`

### Files
- `src/agent/link_store.py`
- `tests/test_link_store.py`
- migration test fixtures

### Tests
- alias resolution by ontology version
- alias cycle detection
- migrations on pre-v1.3 fixture DB
- new columns populated during writes

### Acceptance
- Existing DB opens and migrates without data loss.
- Version-scoped alias resolution works and is deterministic.

---

## PR-3: Runtime Lineage Plumbing

### Goal
Remove placeholder versions and propagate real manifest/ontology/runtime identifiers.

### Implementation
- In `scripts/bulk_family_linker.py` and `scripts/link_worker.py`:
  - derive `corpus_version` from corpus manifest (`agent.corpus.CorpusIndex.get_run_manifest()`), fallback explicit CLI arg
  - derive `parser_version` from parser module version (`agent.parsing_types.__version__` or explicit CLI arg)
  - derive `ontology_version` from ontology metadata adapter
  - derive `git_sha` via `agent.run_manifest.git_commit_hash`
- Add CLI args:
  - `--corpus-version`
  - `--parser-version`
  - `--ontology-version`
  - `--ruleset-version`

### Files
- `scripts/bulk_family_linker.py`
- `scripts/link_worker.py`
- `tests/test_bulk_family_linker.py`
- `tests/test_link_worker.py`

### Acceptance
- No persisted writes use `bulk_linker_v1`, `worker_v1`, `1.0` unless explicitly passed for controlled replay.

---

## PR-4: Calibration Runtime Enforcement + Policy Decisions

### Goal
Make calibration influence runtime outcomes and persist decision semantics.

### Implementation
- In `run_bulk_linking`:
  - fetch scope/template calibration from store
  - pass to `scan_corpus_for_family`
- In candidate build path:
  - persist `score_raw`, `score_calibrated`
  - assign `policy_decision`, `policy_reasons`
- Ensure filtering and status assignment follow policy output.

### Files
- `scripts/bulk_family_linker.py`
- `src/agent/link_confidence.py` (if needed for raw/calibrated split)
- `src/agent/link_store.py`
- tests

### Tests
- threshold boundary tests (high/medium)
- family/template-specific calibration path
- policy reason determinism

### Acceptance
- `/api/links/calibrate/{family_id}` changes actual linking behavior in integration tests.

---

## PR-5: Evidence Contract Completion (Wave 3 Anchor/Lineage)

### Goal
Close evidence schema mismatch and persist stable provenance anchors.

### Implementation
- Extend `_build_candidate` + evidence construction:
  - include `section_reference_key`, `clause_key`, `chunk_id`
  - include run/version tuple
- Normalize evidence save contract so monkeypatch workaround in tests is no longer necessary.
- Ensure clause-level identifiers are carried when available; section-level fallback explicit.

### Files
- `scripts/bulk_family_linker.py`
- `src/agent/link_store.py`
- `tests/test_bulk_family_linker.py`
- `tests/test_link_store.py`

### Acceptance
- Real `save_evidence` path works with production schema (no test-only bypass comments needed).
- Every evidence row is traceable to run + anchor tuple.

---

## PR-6: Export Contract Upgrade (`evidence_v3`, `labeled_export_v2`)

### Goal
Produce strict, versioned Wave 3-compatible handoff payloads.

### Implementation
- `scripts/evidence_collector.py`:
  - add `evidence_v3` with required lineage + anchor fields
  - optional legacy mode via `--schema-version evidence_v2`
- `scripts/export_labeled_data.py`:
  - bump to `labeled_export_v2`
  - strict field validation
  - include lineage completeness checks
- `scripts/link_worker.py::_handle_export`:
  - include export schema version metadata

### Files
- `scripts/evidence_collector.py`
- `scripts/export_labeled_data.py`
- `scripts/link_worker.py`
- tests

### Acceptance
- Export validator rejects missing required Wave 3 fields.
- Legacy mode remains explicit, not default.

---

## PR-7: Governance/Admin Hardening + Audit

### Goal
Harden write endpoint auth and guarantee auditable mutation trail.

### Implementation
- In `dashboard/api/server.py`:
  - constant-time token comparison
  - explicit production guard to reject default token use
- Add audit logging wrapper for all admin mutations:
  - actor fingerprint
  - request host/ip
  - endpoint + mutation type
  - payload hash
  - success/failure
- Ensure calibration endpoint writes audit event.

### Files
- `dashboard/api/server.py`
- `src/agent/link_store.py` (if event metadata extension needed)
- tests

### Acceptance
- Admin mutation endpoints emit durable audit events with actor/context metadata.
- Default token blocked outside dev mode in tests.

---

## PR-8: Backfill Tools + Final Readiness Report

### Goal
Migrate historical artifacts and produce machine-readable readiness signoff.

### Implementation
- Add backfill scripts:
  - schema migration for old export artifacts -> v3/v2
  - lineage enrichment for historical evidence rows where feasible
- Produce readiness docs/artifacts:
  - `docs/operations/wave3-readiness-report-agent.md`
  - `plans/wave3_agent_readiness_gate.json`

### Files
- `scripts/migrate_evidence_schema.py` (new)
- `scripts/backfill_link_lineage.py` (new)
- docs + plan artifact

### Acceptance
- Backfill scripts run idempotently with dry-run and apply modes.
- No P0/P1 open findings remain.

## 6. Global Test Matrix (Run Each PR)

Core:
- `pytest tests/test_link_store.py tests/test_bulk_family_linker.py tests/test_link_confidence.py`
- `pytest tests/test_evidence_collector.py tests/test_clause_parser.py tests/test_clause_gold_fixtures.py`

Parser gate:
- `python3 scripts/parsing_ci_gate.py --mode quick`

Dry-run integration:
- `python3 scripts/bulk_family_linker.py --db corpus_index/corpus.duckdb --links-db corpus_index/links.duckdb --dry-run --family debt_capacity.indebtedness`

Before merge to main (full quality pass where infra exists):
- `python3 scripts/parsing_ci_gate.py --mode full --db corpus_index/corpus.duckdb --collision-baseline data/quality/edge_case_clause_guardrail_baseline.json --parent-baseline data/quality/edge_case_clause_parent_guardrail_baseline.json --thresholds config/parsing_ci_gate_thresholds.json --report artifacts/parsing_ci_gate_full.json`

## 7. Operator Checklist (Per PR)

- [ ] Branch created and scoped to one PR objective.
- [ ] Migrations idempotent and tested against pre-change fixture.
- [ ] New contract fields documented.
- [ ] Tests updated and passing.
- [ ] No placeholder versions in write paths.
- [ ] Changelog note added in PR description.

## 8. PR Acceptance Template (Copy/Paste)

### PR-X Acceptance
- Scope delivered:
  - 
- Files changed:
  - 
- Migration impact:
  - 
- Tests run:
  - command:
  - result:
- Red-team finding(s) closed:
  - 
- Residual risk:
  - 
- Ready to merge: `yes/no`

## 9. Daily Status Template (Copy/Paste)

### Daily Wave 3 Status
- Date:
- Active PR:
- Completed today:
- In progress:
- Blockers:
- Decisions needed:
- Next 24h plan:

## 10. Final Readiness Signoff Template

### Wave 3 Agent Readiness Signoff
- Date:
- Commit SHA:
- Contract versions:
  - evidence schema:
  - export schema:
  - link store schema:
- Gate results:
  - PR-1: pass/fail
  - PR-2: pass/fail
  - PR-3: pass/fail
  - PR-4: pass/fail
  - PR-5: pass/fail
  - PR-6: pass/fail
  - PR-7: pass/fail
  - PR-8: pass/fail
- Open P0/P1 findings: count
- Provenance traceability validated: yes/no
- Recommendation: GO / NO-GO
- Notes:

## 11. Immediate Start Command (PR-1)

Suggested first execution steps:

1. Create branch for PR-1.
2. Implement ontology adapter + matrix normalization.
3. Add tests proving non-empty matrix on current ontology file.
4. Post PR-1 acceptance summary using template section 8.

