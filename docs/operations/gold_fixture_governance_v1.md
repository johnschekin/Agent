# Gold Fixture Governance v1
Date: 2026-02-27
Status: Active
Owner: Parsing Program

## Scope
This workflow governs parser fixtures used by:
1. `scripts/replay_gold_fixtures.py`
2. `scripts/parsing_ci_gate.py`
3. guardrail delta analysis and cutover decisions

## Lifecycle
1. `seed`: candidate rows are generated from parser edge cases and manual findings.
2. `queue`: seeded rows are staged for adjudication with reason codes.
3. `adjudicate`: human review marks expected parse outcome and status tier.
4. `freeze`: accepted rows are promoted into replay fixtures and checksums.
5. `gate`: replay + CI lock checks run on every parser change.

## Canonical Paths
1. seed pool: `data/fixtures/gold/v1/seed/`
2. adjudication queue: `data/fixtures/gold/v1/queue/`
3. frozen fixtures: `data/fixtures/gold/v1/frozen/`
4. replay gates: `data/fixtures/gold/v1/gates/`
5. reason codes: `data/fixtures/gold/v1/reason_codes.v1.json`

## Required Fields Per Fixture Row
1. `fixture_id`
2. `doc_id`
3. `section_number`
4. `input_text`
5. `expected_nodes` (canonical path + parent + depth + status)
6. `status_tier` (`accepted`, `review`, `abstain`)
7. `reason_codes`
8. `adjudicated_by`
9. `adjudicated_at_utc`
10. `schema_version`

## Promotion Rules
1. New fixtures must be schema-valid before queue admission.
2. Frozen fixtures require at least one adjudication pass and zero schema errors.
3. Any fixture edit after freeze requires:
4. a changelog entry
5. manifest checksum refresh
6. replay gate pass

## Gate Contract
Every parser change must pass:
1. `python3 scripts/check_parser_v1_lock.py --manifest data/quality/parser_v1_lock_manifest_2026-02-27.json --json`
2. `python3 scripts/replay_gold_fixtures.py --fixtures data/fixtures/gold/v1/gates/replay_smoke_v1.jsonl --thresholds config/gold_replay_gate_thresholds.json --json`
3. `python3 scripts/parsing_ci_gate.py --mode quick`

## Operating Cadence
1. Daily: seed and queue refresh.
2. Twice weekly: adjudication + freeze promotion window.
3. Weekly: baseline and threshold review against edge-case deltas.

## Change Control
1. Reason-code additions are additive and versioned.
2. Breaking fixture schema changes require:
3. new schema version
4. migration script
5. replay gate updates in same commit
