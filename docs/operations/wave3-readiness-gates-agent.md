# Wave 3 Readiness Gates (Agent)

Status: execution checklist for production readiness
Owner: Wave 3 Readiness Implementation Lead
Date: 2026-02-27

## Gate P0: Contract freeze
- `docs/contracts/ids-v1.md` exists with deterministic formulas and invariants.
- `docs/contracts/evidence-handoff-v1.md` exists with required fields and strict validation rules.
- `docs/contracts/link-authority-v1.md` exists with ontology/alias/governance authority rules.
- Migration note for legacy consumers is documented.

## Gate P1: Parser determinism + anchor completeness
- Determinism test runs same input multiple times and output is byte-identical in structure and IDs.
- Emitted candidates include:
  - `section_path`, `section_reference_key`, `clause_path`, `clause_key`,
  - `node_type`, `span_start`, `span_end`, `anchor_text`.
- Ordering of emitted candidates is stable and test-covered.

## Gate P2: Ontology validation + alias version scoping
- Unknown ontology IDs are rejected at write boundaries.
- Alias resolution is scoped by `ontology_version`.
- Alias cycle detection and orphan detection are enforced and tested.

## Gate P3: Calibration + policy decisions
- Runtime linking loads calibration and applies it in production path.
- Persisted outputs include `score_raw`, `score_calibrated`, `policy_decision`, `policy_reasons`, `threshold_profile_id`.
- Boundary policy tests pass.

## Gate P4: Provenance hardening
- No placeholder version strings in active write paths.
- Every run and evidence row has `run_id`, parser/corpus/ontology/ruleset versions, `git_sha` (if available), `created_at_utc`.
- Repro test can trace row to source document and exact span.

## Gate P5: Wave 3 export + strict validation
- Default export is Wave 3 handoff contract.
- Export validator fails fast on missing/invalid required fields.
- Legacy export requires explicit compatibility flag.

## Gate P6: Governance and admin hardening
- Default insecure token is rejected outside explicit dev mode.
- Sensitive writes require admin authorization.
- Sensitive writes produce immutable audit records.

## Gate P7: Final readiness suite
- Required unit/integration/contract/migration tests pass.
- Red-team regression tests for listed findings are green.
- `docs/operations/wave3-readiness-report-agent.md` generated with:
  - closed findings,
  - remaining risks,
  - commands and outcomes,
  - sample payload paths.

