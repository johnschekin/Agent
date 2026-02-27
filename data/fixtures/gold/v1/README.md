# Gold Fixtures v1

This directory contains the canonical parser-quality fixture assets for:
1. Deterministic parser regression gates.
2. Future ML/LLM training and evaluation.

## Files
1. `fixtures.jsonl`:
2. One JSON object per fixture.
3. Must conform to `gold-fixture-v1` schema contract in `docs/gold-fixture-spec-v1.md`.
4. `reason_codes.v1.json`:
5. Allowed reason-code taxonomy for `review` and `abstain`.
6. `fixture.template.json`:
7. Authoring template for new fixtures.
8. `splits.v1.manifest.json`:
9. Doc-level split assignment and leak checks.

## Authoring Rules
1. Use stable `fixture_id`.
2. Include `source.snapshot_id` for reproducibility.
3. Keep `span_start/span_end` absolute to the section text scope.
4. Use only reason codes listed in `reason_codes.v1.json`.
5. Do not change split assignment without version update and changelog.
