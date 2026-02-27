# Parser V2 Execution Board
Date: 2026-02-27  
Source plan: `plans/parser_v2_comprehensive_implementation_plan_2026-02-27.md`  
Status: Active

## Program Rules
1. Parser v1 is locked during parser_v2 build except critical break/fix.
2. All parser_v2 changes must pass fixture replay + parser CI gate.
3. Dual-run shadow is mandatory before any production cutover.
4. Cutover requires SLO pass for two consecutive runs.

## Critical Path
1. M0 lock and baselines
2. M1 foundations finalization
3. M2 lexer/token model
4. M3 candidate graph
5. M4 solver + abstain
6. M5 adapter + dual-run
7. M6 shadow hardening
8. M7 controlled cutover

## Milestone Board
## M0 Program Freeze and Baseline Lock
Status: `DONE`

Tasks:
1. `M0-T1` Create parser_v1 lock config and freeze/check scripts  
Owner: Agent  
Depends on: none  
Status: `DONE`  
DoD:
1. `config/parser_v1_lock_files.json` exists.
2. `scripts/freeze_parser_v1_lock.py` exists.
3. `scripts/check_parser_v1_lock.py` exists.

2. `M0-T2` Generate parser_v1 lock manifest  
Owner: Agent  
Depends on: `M0-T1`  
Status: `DONE`  
DoD:
1. `data/quality/parser_v1_lock_manifest_2026-02-27.json` generated.
2. Manifest includes file hashes, git SHA, creation timestamp.

3. `M0-T3` Freeze fixture and guardrail baseline references  
Owner: Agent  
Depends on: none  
Status: `DONE`  
DoD:
1. Baseline references recorded in lock manifest.
2. Replay smoke fixture manifest pinned.

4. `M0-T4` Publish parser_v2 contracts v1 draft  
Owner: Agent  
Depends on: none  
Status: `DONE`  
DoD:
1. `docs/contracts/parser-v2-tokens-v1.md`
2. `docs/contracts/parser-v2-candidate-graph-v1.md`
3. `docs/contracts/parser-v2-solution-v1.md`
4. `docs/contracts/parser-v2-status-v1.md`

5. `M0-T5` Run M0 gates and archive report  
Owner: Agent  
Depends on: `M0-T2`, `M0-T3`, `M0-T4`  
Status: `DONE`  
DoD:
1. `python3 scripts/parsing_ci_gate.py --mode quick` passes.
2. `python3 scripts/replay_gold_fixtures.py ...` passes.
3. M0 status summary written.

## M1 Foundations (Hardening)
Status: `DONE`

Tasks:
1. `M1-T1` Finalize fixture governance workflow (`seed -> queue -> adjudicate -> freeze`) — `DONE`
2. `M1-T2` Add parser_v1 lock check to CI quick path. — `DONE`
3. `M1-T3` Establish parser_v2 branch protection checklist. — `DONE`

## M2 Lexer + Token Model
Status: `DONE`

Tasks:
1. `M2-T1` Scaffold `src/agent/parser_v2/normalization.py`. — `DONE`
2. `M2-T2` Scaffold `src/agent/parser_v2/lexer.py`. — `DONE`
3. `M2-T3` Add token schema tests. — `DONE`
4. `M2-T4` Publish token examples and invariants. — `DONE`

## M3 Candidate Graph
Status: `DONE`

Tasks:
1. `M3-T1` Implement candidate node builder. — `DONE`
2. `M3-T2` Implement parent edge candidate generator. — `DONE`
3. `M3-T3` Add graph integrity tests and diagnostics dumps. — `DONE`

## M4 Solver + Confidence/Abstain
Status: `PENDING`

Tasks:
1. `M4-T1` Build deterministic constrained solver MVP.
2. `M4-T2` Implement confidence margin and abstain policy.
3. `M4-T3` Add abstain reason taxonomy mapping.
4. `M4-T4` Add solver-vs-v1 fixture comparison reports.

## M5 Adapter + Dual-Run
Status: `PENDING`

Tasks:
1. `M5-T1` Implement parser_v2 output adapter to existing clause/link contract.
2. `M5-T2` Add parser_v2 sidecar persistence.
3. `M5-T3` Build dual-run script and comparison report.

## M6 Shadow Hardening
Status: `PENDING`

Tasks:
1. `M6-T1` Run dual-run on replay smoke + P0 queue sample.
2. `M6-T2` Run dual-run on shadow corpus slices.
3. `M6-T3` Produce SLO readiness report and manual audit log.

## M7 Controlled Cutover
Status: `PENDING`

Tasks:
1. `M7-T1` Add parser version feature flag and rollback switch.
2. `M7-T2` Cutover dry run in staging mode.
3. `M7-T3` Production cutover after SLO pass and signoff.

## Command Board
M0 commands:
1. `python3 scripts/freeze_parser_v1_lock.py --out data/quality/parser_v1_lock_manifest_2026-02-27.json`
2. `python3 scripts/check_parser_v1_lock.py --manifest data/quality/parser_v1_lock_manifest_2026-02-27.json`
3. `python3 scripts/parsing_ci_gate.py --mode quick --report artifacts/parsing_ci_gate_quick_m0.json`
4. `python3 scripts/replay_gold_fixtures.py --fixtures data/fixtures/gold/v1/gates/replay_smoke_v1.jsonl --thresholds config/gold_replay_gate_thresholds.json --json`

## M0 Progress Log
1. 2026-02-27: Execution board created; M0 started.
2. 2026-02-27: `M0-T1` completed (`config/parser_v1_lock_files.json`, `scripts/freeze_parser_v1_lock.py`, `scripts/check_parser_v1_lock.py`).
3. 2026-02-27: `M0-T2` completed (`data/quality/parser_v1_lock_manifest_2026-02-27.json`).
4. 2026-02-27: `M0-T3` completed (baseline refs pinned in lock config/manifest, replay smoke manifest present).
5. 2026-02-27: `M0-T4` completed (parser_v2 contracts published under `docs/contracts/parser-v2-*.md`).
6. 2026-02-27: `M0-T5` gate run complete and passing (`artifacts/parsing_ci_gate_quick_m0.json` + replay gate pass); pending explicit M0 summary note/commit.
7. 2026-02-27: `M0-T5` completed with status report (`docs/operations/parser_v2_m0_status_2026-02-27.md`).
8. 2026-02-27: `M1-T1` completed (`docs/operations/gold_fixture_governance_v1.md`).
9. 2026-02-27: `M1-T2` completed (parser_v1 lock check added to quick/full gate config).
10. 2026-02-27: `M1-T3` completed (`docs/operations/parser_v2_branch_protection_checklist_v1.md`).
11. 2026-02-27: `M2-T1/M2-T2/M2-T3` completed (`src/agent/parser_v2/*` scaffold + `tests/test_parser_v2_lexer.py`).
12. 2026-02-27: `M2-T4` completed (`docs/contracts/parser-v2-tokens-v1.md` + snapshot fixture `tests/fixtures/parser_v2/token_snapshot_v1.json`).
13. 2026-02-27: `M3-T1/M3-T2/M3-T3` completed (`src/agent/parser_v2/graph_*.py` + `tests/test_parser_v2_graph_builder.py` + diagnostics snapshot fixture).
