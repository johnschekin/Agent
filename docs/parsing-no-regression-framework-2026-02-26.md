# Parsing No-Regression Framework
Date: 2026-02-26  
Scope: section parsing, clause parsing, defined-term parsing, and ontology-link payload fidelity.

## Goal
Allow parser fixes (including x/y parent-loss fixes) while preventing regressions elsewhere.

## Guardrail Layers
1. Unit/fixture correctness
- `tests/test_doc_parser.py`
- `tests/test_zero_section_recovery.py`
- `tests/test_clause_parser.py`
- `tests/test_definitions.py`
- `tests/test_edge_cases.py`

2. Corpus-level parser integrity guardrails
- Collision guardrail: `scripts/edge_case_clause_guardrail.py`
- Parent-loss guardrail: `scripts/edge_case_clause_parent_guardrail.py`
- Shadow reparse diff (no rebuild): `scripts/clause_shadow_reparse_diff.py`

3. Linking payload integrity
- `tests/test_link_worker.py`
- `tests/test_bulk_family_linker.py`

4. UI/contract integrity for edge-cases and links
- `cd dashboard && npx tsc --noEmit`

## Mandatory Pre-Merge Command Set
```bash
pytest -q tests/test_doc_parser.py tests/test_clause_parser.py tests/test_zero_section_recovery.py tests/test_definitions.py -p no:cacheprovider
pytest -q tests/test_edge_cases.py tests/test_edge_case_clause_guardrail.py tests/test_edge_case_clause_parent_guardrail.py -p no:cacheprovider
pytest -q tests/test_link_worker.py tests/test_bulk_family_linker.py -p no:cacheprovider
python3 scripts/edge_case_clause_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_guardrail_baseline.json
python3 scripts/edge_case_clause_parent_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json
python3 scripts/parsing_metric_gate.py --db corpus_index/corpus.duckdb --baseline data/quality/parsing_baseline_freeze_2026-02-27.json --thresholds config/parsing_metric_gate_thresholds.json --json
python3 scripts/clause_shadow_reparse_diff.py --db corpus_index/corpus.duckdb --mode parent-loss --json
cd dashboard && npx tsc --noEmit
```

## Shadow Reparse (No Rebuild)
Use this to verify parser fixes against persisted rows before a full index rebuild.

Focused check (x/y parent-loss targets):
```bash
python3 scripts/clause_shadow_reparse_diff.py \
  --db corpus_index/corpus.duckdb \
  --mode parent-loss \
  --json
```

Broader drift check on sampled sections:
```bash
python3 scripts/clause_shadow_reparse_diff.py \
  --db corpus_index/corpus.duckdb \
  --mode all \
  --limit-sections 500 \
  --fail-on-regression \
  --max-structural-delta-ratio 0.25 \
  --json
```

## x/y Parent-Loss Tracking Standard
Parent-loss is measured by suspicious sections where:
- section has structural depth-1 root `(a)`
- section also has structural depth-1 root `(x)` or `(y)`
- `(a)` clause text itself contains `(x)` or `(y)` (signal that x/y should often be nested)

Tracked metrics (baseline in `data/quality/edge_case_clause_parent_guardrail_baseline.json`):
- `xy_parent_loss.docs`
- `xy_parent_loss.sections`
- `xy_parent_loss.sections_low_root_count`
- `xy_parent_loss.structural_rows`
- `xy_parent_loss.continuation_like_rows`
- `xy_parent_loss.continuation_like_ratio`

## Baseline Policy
- Before parser fix: use current baseline as non-increase guard.
- After parser fix is validated: refresh parent-loss baseline to the improved values.

Baseline refresh command:
```bash
python3 scripts/edge_case_clause_parent_guardrail.py \
  --db corpus_index/corpus.duckdb \
  --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json \
  --write-baseline
```

## Manual Verification Slice (Required)
After parser changes and before merge, manually inspect at least:
- 10 rows from suspicious x/y sections (incremental + ERISA + defaulting lender style headings)
- 10 clause-level rows in ontology query/review preview

Acceptance for manual slice:
- Clause path shown matches actual nested text location.
- Preview highlight lands on the intended clause fragment.
- No new false positives in defined-term previews.

## Rollout Sequence
1. Run full pre-merge command set on current branch.
2. Apply parser fix.
3. Re-run full pre-merge command set.
4. Manually inspect required slice.
5. If parent-loss metrics improve and other gates pass, refresh parent-loss baseline.
6. Merge.

## CI Orchestration
Use the consolidated gate runner for reproducible local/CI execution:

```bash
python3 scripts/parsing_ci_gate.py --mode quick --report artifacts/parsing_ci_gate_quick.json
python3 scripts/parsing_ci_gate.py --mode full --report artifacts/parsing_ci_gate_full.json
```

`full` mode now includes an aggressive corpus metric gate via:
- `scripts/parsing_metric_gate.py`
- thresholds in `config/parsing_metric_gate_thresholds.json`
