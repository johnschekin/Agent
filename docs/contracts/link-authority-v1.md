# Link Authority Contract v1

Status: frozen for Wave 3 governance
Effective date: 2026-02-27

## Authority model

1. Ontology IDs are authoritative only if present in active ontology release.
2. Alias resolution is authoritative only within the same `ontology_version`.
3. Link write acceptance depends on deterministic policy evaluation and anchor validity.

## Alias policy

1. Alias mapping is keyed by `(legacy_family_id, ontology_version)`.
2. Resolver must reject:
- orphan aliases (canonical target not in ontology release),
- ambiguous aliases (multiple canonical targets in same ontology version),
- cycles (detected by graph traversal).
3. Resolver behavior must be deterministic:
- stable traversal order,
- stable selected canonical node for same inputs.

## Ontology validation contract

1. Unknown `ontology_node_id` must fail fast before persistence.
2. Required family relationships (as defined by ontology adapter/contract) must validate before rule or link write.
3. Conflict matrix build must fail in strict mode if ontology loads but yields zero policies.

## Decision logging contract

Every accepted or rejected link candidate must persist:
- `policy_decision`,
- `policy_reasons`,
- `ontology_version`,
- `threshold_profile_id`,
- run provenance fields from `evidence-handoff-v1.md`.

## Governance audit expectations

Admin mutations (rules, calibrations, manual link operations) must emit immutable audit records with:
- actor identity/fingerprint,
- request id,
- source host/ip metadata,
- mutation type and payload hash,
- timestamp (UTC).

## Unresolved items

None. Defaults from D1-D5 are locked for this release.

