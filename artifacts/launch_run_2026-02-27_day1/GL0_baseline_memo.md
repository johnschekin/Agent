# GL0 Baseline Memo (Day 1)
Date: 2026-02-27
Run ID: launch_run_2026-02-27_day1
Owner: Parser Tech Lead (Codex execution)

## Forensic Provenance
Canonical run manifest:
1. `artifacts/launch_run_2026-02-27_day1/day1_run_manifest.json`

Key provenance fields:
1. Git commit SHA: `0f4a6a350551d0b22036ff723373598bd4a5a6b9`
2. Parser engine/version: `parser_v1@0.1.0`
3. Parser primary artifact fingerprint (`clause_parser.py` SHA256):
4. `a761df6d360ab41d86a7c066ff2ff4a7a1ba673b9eb2b63cafb638337bf295e3`
5. Parser fingerprint manifest:
6. `artifacts/launch_run_2026-02-27_day1/parser_fingerprints.json`
7. Corpus build ID: `ray_v2_corpus_build_20260227T041350Z_4e318cf8`
8. Corpus build manifest SHA256: `4d9d62eea744478e788d3309f0290b2e831b17a27d35c1e739f556e9185f9d21`
9. Replay threshold snapshot:
10. `artifacts/launch_run_2026-02-27_day1/gold_replay_gate_thresholds.snapshot.json`
11. Clause guardrail baseline snapshot:
12. `artifacts/launch_run_2026-02-27_day1/edge_case_clause_guardrail_baseline.snapshot.json`
13. Parent guardrail baseline snapshot:
14. `artifacts/launch_run_2026-02-27_day1/edge_case_clause_parent_guardrail_baseline.snapshot.json`
15. Workspace dirty-state snapshot:
16. `artifacts/launch_run_2026-02-27_day1/workspace_dirty_status.snapshot.txt`
17. Clean-source verification folder:
18. `artifacts/launch_run_2026-02-27_day1/clean_source/`
19. Canonical selection policy (enforced):
20. `artifacts/launch_run_2026-02-27_day1/day1_canonical_selection_policy.json`
21. Canonical output folder:
22. `artifacts/launch_run_2026-02-27_day1/canonical/`
23. Canonical routing enforcement report:
24. `artifacts/launch_run_2026-02-27_day1/day1_canonical_enforcement_report.json`

## Commands Executed
1. `python3 scripts/validate_gold_fixtures.py --fixtures data/fixtures/gold/v1/fixtures.jsonl --json`
2. `python3 scripts/replay_gold_fixtures.py --fixtures data/fixtures/gold/v1/fixtures.jsonl --json`
3. `python3 scripts/edge_case_clause_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_guardrail_baseline.json --json`
4. `python3 scripts/edge_case_clause_parent_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json --json`
5. `pytest -q tests/test_clause_parser.py tests/test_doc_parser.py tests/test_document_processor.py tests/test_edge_cases.py tests/test_zero_section_recovery.py -p no:cacheprovider`
6. `pytest -q tests/test_clause_parser.py tests/test_doc_parser.py tests/test_document_processor.py tests/test_edge_cases.py tests/test_zero_section_recovery.py -p no:cacheprovider` (day1.1 rerun after pytest-asyncio config hardening)
7. Clean-source verification (in clean worktree `/tmp/agent_day1_clean_repro`):
8. `python3 scripts/validate_gold_fixtures.py --fixtures /Users/johnchtchekine/Projects/Agent/data/fixtures/gold/v1/fixtures.jsonl --json`
9. `python3 scripts/replay_gold_fixtures.py --fixtures /Users/johnchtchekine/Projects/Agent/data/fixtures/gold/v1/fixtures.jsonl --json`
10. `python3 scripts/edge_case_clause_guardrail.py --db /Users/johnchtchekine/Projects/Agent/corpus_index/corpus.duckdb --baseline /Users/johnchtchekine/Projects/Agent/data/quality/edge_case_clause_guardrail_baseline.json --json`
11. `python3 scripts/edge_case_clause_parent_guardrail.py --db /Users/johnchtchekine/Projects/Agent/corpus_index/corpus.duckdb --baseline /Users/johnchtchekine/Projects/Agent/data/quality/edge_case_clause_parent_guardrail_baseline.json --json`
12. `pytest -q tests/test_clause_parser.py tests/test_doc_parser.py tests/test_document_processor.py tests/test_edge_cases.py tests/test_zero_section_recovery.py -p no:cacheprovider`

## Artifact Bundle
1. `artifacts/launch_run_2026-02-27_day1/validate_gold_fixtures.json`
2. `artifacts/launch_run_2026-02-27_day1/replay_gold_fixtures.json`
3. `artifacts/launch_run_2026-02-27_day1/edge_case_clause_guardrail.json`
4. `artifacts/launch_run_2026-02-27_day1/edge_case_clause_parent_guardrail.json`
5. `artifacts/launch_run_2026-02-27_day1/parser_v1_tests.log`
6. `artifacts/launch_run_2026-02-27_day1/day1_1_blocker_register.json`
7. `artifacts/launch_run_2026-02-27_day1/day1_failure_slice_top15.json`
8. `artifacts/launch_run_2026-02-27_day1/day1_run_manifest.json`
9. `artifacts/launch_run_2026-02-27_day1/parser_fingerprints.json`
10. `artifacts/launch_run_2026-02-27_day1/workspace_dirty_status.snapshot.txt`
11. `artifacts/launch_run_2026-02-27_day1/clean_source/*`
12. `artifacts/launch_run_2026-02-27_day1/day1_clean_source_comparison.json`
13. `artifacts/launch_run_2026-02-27_day1/day1_canonical_selection_policy.json`
14. `artifacts/launch_run_2026-02-27_day1/canonical/*`

## Results Summary
1. Fixture schema validation: PASS (`ok=true`).
2. Parser replay gate (canonical): PASS.
3. Clause guardrail: PASS.
4. Parent-loss guardrail: FAIL.
5. Parser_v1-focused test suite: PASS (`218 passed`).
6. Dirty-workspace replay (diagnostic-only): FAIL (`56` failed fixtures).

Replay fail highlights:
1. `fixtures_failed=56` (all in `accepted`).
2. Category breaches: `deep_nesting_chain=50` (budget 4), `linking_contract=6` (budget 4).
3. Failure reason mode: `field_mismatch_ratio_above_threshold` only.
4. Mismatch field concentration: `is_structural` drift with node/span precision/recall at `1.0`.
5. Attribution update: clean-source replay at same commit passes; dirty-run replay failure is workspace-drift-contaminated evidence.

Parent guardrail fail highlights:
1. `xy_parent_loss.docs`: baseline 294 -> current 432.
2. `xy_parent_loss.sections`: baseline 318 -> current 523.
3. `xy_parent_loss.structural_rows`: baseline 378 -> current 703.
4. `xy_parent_loss.continuation_like_rows`: baseline 184 -> current 197.

## Command Exit Codes
1. `validate_gold_fixtures`: `0`
2. `replay_gold_fixtures`: `0` (canonical)
3. `edge_case_clause_guardrail`: `0`
4. `edge_case_clause_parent_guardrail`: `1`
5. `parser_v1_tests`: `0`

Exit code files:
1. `artifacts/launch_run_2026-02-27_day1/canonical/validate_gold_fixtures.exit_code`
2. `artifacts/launch_run_2026-02-27_day1/canonical/replay_gold_fixtures.exit_code`
3. `artifacts/launch_run_2026-02-27_day1/canonical/edge_case_clause_guardrail.exit_code`
4. `artifacts/launch_run_2026-02-27_day1/canonical/edge_case_clause_parent_guardrail.exit_code`
5. `artifacts/launch_run_2026-02-27_day1/canonical/parser_v1_tests.exit_code`
6. Dirty/diagnostic exit codes retained in root run directory.

## Clean-Source Verification
1. Clean worktree commit matches run commit SHA.
2. Replay divergence observed:
3. Dirty run replay: `fail` (56 failed fixtures).
4. Clean-source replay: `pass` (0 failed fixtures).
5. Guardrail parity remained:
6. Clause guardrail `pass`, parent guardrail `fail`.
7. Canonical baseline attribution is now enforced via canonical selection policy and manifest primary pointers.

## Canonical Routing Enforcement
1. Primary output pointers in `day1_run_manifest.json` now target:
2. `artifacts/launch_run_2026-02-27_day1/canonical/*`
3. Dirty replay artifact is explicitly marked diagnostic-only.
4. Executable enforcement check is now active:
5. `python3 scripts/enforce_canonical_gate_artifacts.py --manifest artifacts/launch_run_2026-02-27_day1/day1_run_manifest.json --json`
6. Enforcement report status: `pass`.
7. Provenance blocker `BLK-D1-PROV-002` status is now `closed`.

## GL0 Decision
`NO-GO` for GL0 pass on this run.

Blocking reasons:
1. Parent-loss guardrail regressions (clean-source confirmed).
2. No additional provenance blocker; canonical routing now resolves dirty-vs-clean replay attribution for gate consumption.

## Blocker Register (Day 1.1)
1. `BLK-D1-PARENT-001` owner `Parser Engineer`, ETA `2026-03-02T00:00:00Z` (open).
2. `BLK-D1-REPLAY-001` status `closed` (re-attribution complete, diagnostic-only).
3. `BLK-D1-PROV-002` status `closed` (canonical routing enforced).
4. Full details in:
5. `artifacts/launch_run_2026-02-27_day1/day1_1_blocker_register.json`

## Minimal Failure Slice
1. Top replay failing fixtures and mismatch concentration:
2. `artifacts/launch_run_2026-02-27_day1/day1_failure_slice_top15.json`
3. Top parent-loss sections from current snapshot included in same artifact.

## Test Warning Hardening
1. Added pytest config key `asyncio_default_fixture_loop_scope = "function"` in `pyproject.toml`.
2. Re-ran parser_v1 test slice with warning removed:
3. `artifacts/launch_run_2026-02-27_day1/parser_v1_tests_day1_1.log`
4. Exit code:
5. `artifacts/launch_run_2026-02-27_day1/parser_v1_tests_day1_1.exit_code`

Per binding clarification Q17, no baseline refresh/rebaseline was performed; this is treated as fail-to-investigate.

## Sign-off
Prepared by: Codex
Prepared at: 2026-02-27 (local run)
