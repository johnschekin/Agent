# Parser V2 Branch Protection Checklist v1
Date: 2026-02-27
Status: Active
Owner: Parsing Program

## Objective
Protect parser_v1 behavior while parser_v2 is built in parallel.

## Mandatory Branch Rules
1. Require passing checks before merge:
2. parsing CI gate (`quick` at minimum)
3. replay smoke gate
4. parser_v1 lock check
5. Disallow direct commits to protected integration branches.
6. Require linear history or squash merges only.
7. Require one code-owner review for parser core paths.

## Protected Paths
1. `src/agent/clause_parser.py`
2. `src/agent/enumerator.py`
3. `src/agent/parsing_types.py`
4. `scripts/parsing_ci_gate.py`
5. `scripts/replay_gold_fixtures.py`
6. `scripts/edge_case_clause_guardrail.py`
7. `scripts/edge_case_clause_parent_guardrail.py`
8. `tests/test_clause_parser.py`
9. `tests/test_clause_tree_invariants.py`
10. `tests/test_clause_gold_fixtures.py`
11. `tests/test_replay_gold_fixtures.py`

## PR Checklist
1. Parser-v1 lock manifest unchanged unless explicitly regenerated.
2. If lock manifest changes, include rationale and reviewer signoff.
3. Replay smoke fixture manifest unchanged unless intended fixture promotion.
4. Any threshold change includes before/after delta report.
5. New parser_v2 modules include deterministic tests.

## Required Command Bundle
1. `python3 scripts/check_parser_v1_lock.py --manifest data/quality/parser_v1_lock_manifest_2026-02-27.json --json`
2. `python3 scripts/parsing_ci_gate.py --mode quick --report artifacts/parsing_ci_gate_quick.json`
3. `python3 scripts/replay_gold_fixtures.py --fixtures data/fixtures/gold/v1/gates/replay_smoke_v1.jsonl --thresholds config/gold_replay_gate_thresholds.json --json`

## Escalation Rule
If any parser-v1 lock check fails:
1. block merge
2. require explicit parser-v1 drift approval
3. document impact and rollback plan
