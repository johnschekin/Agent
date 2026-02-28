# Parser V2 M6.5 Quality Lift Report
Date: 2026-02-27
Owner: Parsing Program
Status: Completed (`M6.5` exploratory quality-lift pass)

## Scope
Targeted logic updates to reduce over-conservative parser_v2 statusing pressure concentrated in:
1. `low_margin`
2. `xref_conflict`

Re-ran the same M6-T2 shadow slices (2,600 sections total) to measure delta.

## Code Changes
1. `src/agent/parser_v2/lexer.py`
1. Tightened xref-pre context extraction to tail-context patterns instead of broad lookback keyword matching.
2. Reduced false preposition-triggering by requiring legal noun context near token boundary.

2. `src/agent/parser_v2/solver.py`
1. Added strong-layout margin relief for anchored line-start tokens.
2. Added low-margin promotion guard for strong anchored tokens.
3. Converted a subset of near-threshold abstains to review when structural signals are strong.

3. Contract test updates
1. `tests/test_parser_v2_solver.py`
2. `tests/fixtures/parser_v2/token_snapshot_v1.json`
3. `tests/fixtures/parser_v2/solver_snapshot_v1.json`

## Validation
1. `pytest -q tests/test_parser_v2_lexer.py tests/test_parser_v2_solver.py -p no:cacheprovider` -> pass
2. `pytest -q tests/test_parser_v2_dual_run.py tests/test_parser_v2_adapter.py tests/test_parser_v2_graph_builder.py -p no:cacheprovider` -> pass
3. `python3 -m py_compile src/agent/parser_v2/solver.py src/agent/parser_v2/lexer.py` -> pass

## Shadow Slice Re-run (same M6-T2 packs)
Reports:
1. `artifacts/parser_v2_dual_run_report_m6_5_fixtures500.json`
2. `artifacts/parser_v2_dual_run_report_m6_5_candidate1000.json`
3. `artifacts/parser_v2_dual_run_report_m6_5_hard1000.json`
4. `artifacts/parser_v2_dual_run_report_m6_5_edgecases100.json`

Delta summary artifact:
1. `artifacts/parser_v2_m6_5_delta_summary.json`
2. `artifacts/parser_v2_m6_5_reason_diagnostics.json`

## Aggregate Delta (2,600 sections)
Baseline (`M6-T2/M6-T3`):
1. accepted: `7` (`0.269%`)
2. review: `112` (`4.308%`)
3. abstain: `2,481` (`95.423%`)
4. avg overlap: `0.107459`

After M6.5:
1. accepted: `10` (`0.385%`)
2. review: `1,265` (`48.654%`)
3. abstain: `1,325` (`50.962%`)
4. avg overlap: `0.108256`

Net:
1. accepted: `+3`
2. review: `+1,153`
3. abstain: `-1,156`
4. avg overlap: `+0.000797`

## Reason-Code Movement
1. `low_margin` remains dominant at section level (`2,590`) -> unresolved core blocker.
2. `xref_conflict` section-level frequency decreased materially (`2,538` -> `1,926`).
3. `insufficient_context` fell with abstain volume (`2,481` -> `1,325`) but remains high.

## Interpretation
1. This pass succeeded at moving many sections out of abstain into review.
2. It did not create a meaningful accepted-rate lift.
3. Primary blocker remains unresolved margin separation (`low_margin`) in ambiguous token decisions.

## Verdict
`NOT READY` for M7 cutover.

## Recommended Next Step (M6.6)
1. Add deterministic context features for ambiguous alpha/roman tokens (forward/backward run continuity signals at token-decision time).
2. Score parent-edge coherence before final token statusing to improve margin spread.
3. Add category-aware promotion only for tightly-defined low-risk classes after manual spot-audit.
4. Re-run the same 2,600-section shadow packs and require accepted-rate lift beyond noise before M7-T1.
