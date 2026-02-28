# Parser V2 M6-T2 Shadow Report
Date: 2026-02-27  
Owner: Parsing Program  
Status: Completed (`M6-T2`)

## Scope
Ran parser_v1 vs parser_v2 dual-run on larger slices and produced category/scope deltas.

## Commands
1. `python3 scripts/parser_v2_dual_run.py --fixtures data/fixtures/gold/v1/fixtures.jsonl --limit 500 --sidecar-out artifacts/parser_v2_dual_run_sidecar_fixtures500.jsonl --report-out artifacts/parser_v2_dual_run_report_fixtures500.json --overwrite-sidecar --json`
2. `python3 scripts/parser_v2_dual_run.py --fixtures data/fixtures/gold/v1/packs/v1-seed-hard-2500/fixtures.jsonl --limit 1000 --sidecar-out artifacts/parser_v2_dual_run_sidecar_hard1000.jsonl --report-out artifacts/parser_v2_dual_run_report_hard1000.json --overwrite-sidecar --json`
3. `python3 scripts/parser_v2_dual_run.py --fixtures data/fixtures/gold/v1/packs/v1-seed-1000-candidate/fixtures.jsonl --limit 1000 --sidecar-out artifacts/parser_v2_dual_run_sidecar_candidate1000.jsonl --report-out artifacts/parser_v2_dual_run_report_candidate1000.json --overwrite-sidecar --json`
4. `python3 scripts/parser_v2_dual_run.py --fixtures data/quality/clause_edge_cases_batch_1.jsonl --limit 100 --sidecar-out artifacts/parser_v2_dual_run_sidecar_edgecases100.jsonl --report-out artifacts/parser_v2_dual_run_report_edgecases100.json --overwrite-sidecar --json`

## Aggregated Output
Consolidated summary artifact:
1. `artifacts/parser_v2_dual_run_m6_t2_summary.json`

Combined totals across 2,600 sections:
1. `accepted`: 7
2. `review`: 112
3. `abstain`: 2,481
4. `avg_id_overlap_ratio`: `0.107459`

By slice:
1. `fixtures500`: 500 rows, abstain rate `0.928`, avg overlap `0.107733`
2. `hard1000`: 1000 rows, abstain rate `0.988`, avg overlap `0.087432`
3. `candidate1000`: 1000 rows, abstain rate `0.933`, avg overlap `0.120448`
4. `edgecases100`: 100 rows, abstain rate `0.960`, avg overlap `0.176482`

## Category Breakdown (largest stress groups)
1. `ambiguous_alpha_roman`: 810 rows, abstain `790` (`0.975309`), overlap `0.02025`
2. `high_letter_continuation`: 710 rows, abstain `706` (`0.994366`), overlap `0.152327`
3. `nonstruct_parent_chain`: 190 rows, abstain `176` (`0.926316`), overlap `0.018372`
4. `xref_vs_structural`: 180 rows, abstain `138` (`0.766667`), overlap `0.376731`
5. `true_root_high_letter`: 130 rows, abstain `123` (`0.946154`), overlap `0.234585`
6. `duplicate_collision`: 105 rows, abstain `105` (`1.0`), overlap `0.013607`

## Article-Scope Breakdown
1. Article scope `1`: 1202 rows, abstain `1191` (`0.990849`), overlap `0.020912`
2. Article scope `6`: 300 rows, abstain `293` (`0.976667`), overlap `0.221711`
3. Article scope `2`: 263 rows, abstain `230` (`0.874525`), overlap `0.206132`
4. Article scope `7`: 223 rows, abstain `210` (`0.941704`), overlap `0.240701`

## Interpretation
1. Current solver thresholds are too conservative for production usage.
2. Main concentration of abstentions is in:
3. alpha/roman ambiguity
4. high-letter continuation
5. non-structural parent-chain patterns
6. Overlap is materially better for `xref_vs_structural` than most other categories, suggesting targeted threshold tuning can recover coverage there first.

## Notes
1. `p0_adjudication_queue_200.jsonl` contains queue metadata only and no raw text payload, so it is not directly runnable by dual-run.
2. Equivalent content coverage for queue-linked fixtures was captured via `v1-seed-1000-candidate`.
