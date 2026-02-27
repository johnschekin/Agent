# Wave 3 Readiness Report (Agent)

Date: 2026-02-27  
Git SHA: `68da7d8`  
Owner: Wave 3 Readiness Implementation Lead

## Scope

This report certifies Agent-side readiness for Neutron Wave 3 ontology-linked clause/section extraction handoff, including deterministic IDs, enforced lineage non-placeholder policy, strict export validation, and auditable governance.

## Gate Status

| Gate | Status | Notes |
| --- | --- | --- |
| P0 Contract freeze | PASS | Contracts finalized in `docs/contracts/*.md`; examples + invariants included. |
| P1 Determinism + anchors | PASS | Deterministic ordering + canonical IDs/anchors (`section_reference_key={document_id}:{section_number}`). |
| P2 Ontology validation + alias scoping | PASS | Adapter + conflict matrix + ontology-version-scoped aliasing + ambiguity guards. |
| P3 Calibration + policy | PASS | Runtime calibration applied in bulk linker path with deterministic policy decisions. |
| P4 Provenance hardening | PASS | Placeholder lineage blocked in runtime writes; historical run/link/evidence lineage remediated to non-placeholder values. |
| P5 Wave3 export + validation | PASS | Default export remains Wave3 handoff with strict required-field validation (including lineage tuple). |
| P6 Governance/admin hardening | PASS | Constant-time auth checks, role-based controls, success/failure mutation audit events. |
| P7 Final readiness suite | PASS | Mandatory tests, parsing gate, strict-ontology dry-run, migration/backfill checks all green. |

## Blocker Closure

1. Historical lineage remediation:
   - `scripts/backfill_link_lineage.py` now repairs `family_link_runs` lineage first, then propagates to `family_links` and `link_evidence`.
   - Main DB run (`corpus_index/links.duckdb`) result:
     - `family_link_runs_bad`: `43 -> 0`
     - `family_links_bad`: `48346 -> 0`
     - `link_evidence_bad`: `2001 -> 0`
   - Re-run is idempotent (`0` deltas on second apply run).
2. Placeholder lineage generation in bulk runtime:
   - `scripts/bulk_family_linker.py` now synthesizes non-placeholder deterministic runtime lineage and validates before write path usage.
   - Hard guard rejects placeholder/empty lineage fields.
3. Stale readiness artifacts:
   - Report and machine-readable gate artifacts regenerated on current SHA (`68da7d8`).

## Commands Executed and Outcomes

1. `pytest tests/test_link_store.py tests/test_bulk_family_linker.py tests/test_link_confidence.py`
   - exit `0`, `235 passed`
2. `pytest tests/test_evidence_collector.py tests/test_clause_parser.py tests/test_clause_gold_fixtures.py`
   - exit `0`, `69 passed`
3. `python3 scripts/parsing_ci_gate.py --mode quick`
   - exit `0`, `ok: true`
4. `python3 scripts/bulk_family_linker.py --db corpus_index/corpus.duckdb --links-db corpus_index/links.duckdb --dry-run --family debt_capacity.indebtedness --strict-ontology > artifacts/wave3_handoff_candidate_sample.json`
   - exit `0`, conflict matrix built (`241` pairs), `668` candidates
5. `python3 scripts/backfill_link_lineage.py --links-db corpus_index/links.duckdb`
   - exit `0`, lineage bad counts reduced to zero for runs/links/evidence
6. `python3 scripts/backfill_link_lineage.py --links-db corpus_index/links.duckdb`
   - exit `0`, idempotence verified (`delta=0` across all bad-count metrics)
7. `python3 scripts/migrate_evidence_schema.py --input artifacts/wave3_workspace/evidence/debt_capacity.indebtedness_20260227T045755.jsonl --output artifacts/wave3_workspace/migrations/plan_wrapper_out.jsonl`
   - exit `0`, deterministic output checksum stable across rerun

## Sample Artifacts

- `artifacts/wave3_handoff_candidate_sample.json`
- `artifacts/wave3_workspace/results/wave3_labeled.jsonl`
- `artifacts/wave3_workspace/migrations/plan_wrapper_out.jsonl`
- `plans/wave3_agent_readiness_gate.json`
- `artifacts/wave3-readiness-gates-agent.json`

## Remaining Risks

1. Ontology policy behavior still depends on ontology source quality; production runs should keep `--strict-ontology` enabled.
2. Legacy downstream consumers still need explicit compatibility mode while migrating off legacy contracts.

## Decision Log (No Silent Deferrals)

1. D1 Canonical IDs locked and enforced (`section_reference_key={document_id}:{section_number}`).
2. D2 Confidence policy locked (`must/review/reject`) and persisted with machine-readable reasons.
3. D3 Versioning locked; placeholder lineage rejected in runtime writes and remediated in historical rows.
4. D4 Alias policy locked to ontology-version scope with cycle/orphan/ambiguity failure behavior.
5. D5 Export contract locked to Wave3 handoff default, legacy mode explicit only.
6. Deferrals made without user approval: none.
