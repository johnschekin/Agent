# Agent Evidence Handoff v1 (Wave 3)

Status: default export contract for Neutron Wave 3
Effective date: 2026-02-27

## Purpose
Defines strict row-level payload required for ontology binding, provenance, governance, and deterministic replay.

## Required row fields

Identity:
- `chunk_id`
- `document_id`
- `section_reference_key`
- `clause_key`
- `ontology_node_id`

Anchor:
- `node_type` (`section` or `clause`)
- `section_path`
- `clause_path`
- `span_start`
- `span_end`
- `anchor_text`
- `text_sha256`

Scoring and policy:
- `score_raw`
- `score_calibrated`
- `threshold_profile_id`
- `grounded` (boolean)
- `policy_decision` in `{must, review, reject}`
- `policy_reasons` (machine-readable JSON array of reason codes)

Provenance:
- `run_id`
- `corpus_snapshot_id`
- `corpus_version`
- `parser_version`
- `ontology_version`
- `ruleset_version`
- `git_sha` (nullable only when unavailable in runtime)
- `source_document_path` (sanitized, stable)
- `created_at_utc` (ISO 8601 UTC)

## Policy decision contract

1. `must`:
- `score_calibrated >= must_threshold`
- `grounded == true`

2. `review`:
- `score_calibrated >= review_threshold`
- or (`grounded == false` and evidence minimum satisfied)

3. `reject`:
- below review threshold
- or invalid anchor
- or invalid ontology mapping

## Invariants

1. Every exported row must be independently traceable to one source span and one ontology node.
2. `policy_reasons` must include at least one reason for `review` and `reject`.
3. Row must fail validation if any required identity, anchor, or provenance field is missing.
4. `chunk_id` must verify against canonical formula from `ids-v1.md`.

## Compatibility and migration note

- Default export path is Wave 3 handoff.
- Legacy export is still available only through explicit compatibility mode (`--format legacy-v0` or schema override flags).
- Existing consumers of `evidence_v2` and `labeled_export_v1` must opt into compatibility mode during migration; compatibility mode is non-default by design.

## Example handoff row

```json
{
  "chunk_id": "b7f4b3e190cd54f77ea8420a0a18a572ba30f2246ba76397cb0c4bfc6cf966e4",
  "document_id": "2b70f8ca4d92a8b1f1d7f4e1ea9a9967f5cbe57f482cb9f22857dcf0176fa0aa",
  "section_reference_key": "2b70f8ca4d92a8b1f1d7f4e1ea9a9967f5cbe57f482cb9f22857dcf0176fa0aa:7.02",
  "clause_key": "2b70f8ca4d92a8b1f1d7f4e1ea9a9967f5cbe57f482cb9f22857dcf0176fa0aa:7.02:a.1.i",
  "ontology_node_id": "debt_capacity.indebtedness.other_debt",
  "node_type": "clause",
  "section_path": "7.02",
  "clause_path": "a.1.i",
  "span_start": 4901,
  "span_end": 5112,
  "anchor_text": "other indebtedness ...",
  "text_sha256": "d9f2f06be4d8ba32dc86f7f45fd3d36f5a39d09faf5f3e90a4e8f7ff7868fc8b",
  "score_raw": 0.74,
  "score_calibrated": 0.81,
  "threshold_profile_id": "family:debt_capacity.indebtedness:v2026-02-27",
  "grounded": true,
  "policy_decision": "must",
  "policy_reasons": ["threshold.must.met", "grounded.true"],
  "run_id": "run_20260227_223744_4d5f",
  "corpus_snapshot_id": "corpus_v2026_02_27_2100",
  "corpus_version": "corpus-index-v0.2.0",
  "parser_version": "clause-parser-v2026-02-27",
  "ontology_version": "ontology-v2026-02-20",
  "ruleset_version": "rules-v2026-02-27",
  "git_sha": "9f1e5c4",
  "source_document_path": "corpus/contracts/acme-credit-agreement.txt",
  "created_at_utc": "2026-02-27T23:10:44Z"
}
```
