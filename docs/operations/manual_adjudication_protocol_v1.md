# Manual Adjudication Protocol v1
Date: 2026-02-27
Status: Active
Owner: Data/Adjudication Lead
Approved in run: `launch_run_2026-02-27_day2`

## Scope
This protocol governs human adjudication rows used for:
1. GL1 label-quality gate evidence.
2. Edge-case model training/export inputs.
3. Shadow and canary audit replay.

In-scope edge-case classes:
1. `ambiguous_alpha_roman`
2. `high_letter_continuation`
3. `xref_vs_structural`
4. `nonstruct_parent_chain`

## Hard Policy
1. Adjudication is human-authored only; no auto-labeling.
2. Adjudication logs are immutable, versioned artifacts.
3. Queue files store operational status only and reference adjudication IDs.
4. Every adjudication row must include witness text and comparative reasoning.

## Storage Model
1. Queue rows remain in `data/fixtures/gold/v1/adjudication/p0_adjudication_queue_*.jsonl`.
2. Adjudication rows are written to versioned logs under:
3. `data/fixtures/gold/v1/adjudication/logs/`
4. Canonical row schema version: `manual-adjudication-log-v1`.

## Required Row Schema
Required fields per adjudication row:
1. `schema_version` (`manual-adjudication-log-v1`)
2. `adjudication_id`
3. `row_id`
4. `queue_item_id`
5. `fixture_id`
6. `doc_id`
7. `section_number`
8. `edge_case_class`
9. `witness_snippets`
10. `candidate_interpretations`
11. `decision`
12. `decision_rationale`
13. `confidence_level`
14. `adjudicator_id`
15. `adjudicated_at`
16. `corpus_build_id`
17. `section_text_sha256`
18. `doc_text_sha256`
19. `source_snapshot_id`

Optional fields:
1. `fixture_snapshot_tag`
2. `notes`

## Required Reasoning Content
For each row:
1. `witness_snippets` must contain at least one concrete quote/snippet.
2. `candidate_interpretations` must contain both hypothesis `A` and `B`.
3. Each hypothesis entry must include:
4. `interpretation`
5. `survives` (`true|false`)
6. `reason`
7. `decision_rationale` must be explicit and non-trivial prose.

## Provenance Contract
1. `source_snapshot_id` format is:
2. `{corpus_build_id}:{section_text_sha256}`
3. `section_text_sha256` and `doc_text_sha256` must be lowercase 64-char hex.
4. `doc_id` and `section_number` are mandatory provenance keys and are stored separately.

## Decision and Confidence
Allowed decisions:
1. `accepted`
2. `review`
3. `abstain`

Allowed confidence levels:
1. `low`
2. `medium`
3. `high`

## Batch Workflow
1. Adjudicate in batches of 20 queue rows.
2. Validate each batch with:
3. `python3 scripts/validate_manual_adjudication_log.py --log <batch_file> --json`
4. Append validated rows to a new immutable versioned log file.
5. Update queue state with adjudication references only after validation passes.

## GL1 Quality Targets
1. Total labels: `>=800`
2. Per-class minimum: `>=150`
3. Target balance: `200/class`
4. Acceptable range: `150-250/class`
5. Re-audit consistency: `>=95%` on random 10% sample
6. Escalation rate after first 400 rows: `<=15%`

## Validator Contract
The validator fails on:
1. Missing required fields.
2. Missing witness snippets.
3. Missing comparative reasoning (missing hypothesis A/B or missing hypothesis reasoning).
4. Invalid provenance or snapshot ID mismatch.
5. Invalid decisions/confidence values.

Optional GL1 threshold checks:
1. Enable with `--enforce-gl1-thresholds`.
2. Enforces total-volume and per-class min/max requirements.
