# Indebtedness Pilot Protocol (Stage 2)

Authoritative gate sequencing is defined in:
- `plans/master_rollout_plan.md`
- `plans/master_execution_backlog_p0_p2.md`

This protocol runs the first end-to-end ontology-to-clause workflow for
`debt_capacity.indebtedness` and five L2 children.

## 0) Preconditions

- Stage 1/1.5 non-dashboard gates are passing for your target DB.
- A corpus DB exists (recommended: full-cohort DB at Gate 2+).
- `workspaces/indebtedness/context/ontology_subtree.json` is present.

## 1) Set Paths

```bash
export PYTHONPATH=src
export DB=/tmp/agent_stage1_run_500/corpus_index/stage1_500.duckdb
export WS=workspaces/indebtedness
export STRAT_DIR=$WS/strategies
```

Replace `DB` with your active corpus index when running at larger scale.

## 2) Prepare/Refresh Workspace

```bash
python3 scripts/setup_workspace.py \
  --family indebtedness \
  --expert-materials ~/Projects/TermIntelligence/analysis/indebtedness \
  --ontology data/ontology/r36a_production_ontology_v2.5.1.json \
  --bootstrap data/bootstrap/bootstrap_all.json
```

## 3) Build Gold-Set Candidate Slice

If `workspaces/indebtedness/results/gold_set.jsonl` already exists, keep it and append.

```bash
python3 scripts/sample_selector.py \
  --db "$DB" \
  --n 50 \
  --stratify template_family \
  --seed 42 \
  --output "$WS/results/gold_docs.txt"
```

Label 40 docs for evaluation and reserve 10 docs as blind holdout.

## 4) Map Structural Priors

Family-level structural map:

```bash
python3 scripts/structural_mapper.py \
  --db "$DB" \
  --strategy "$STRAT_DIR/debt_capacity.indebtedness.general_basket_v001.json" \
  --sample 500
```

Discover heading variants with canonical concept hints:

```bash
python3 scripts/heading_discoverer.py \
  --db "$DB" \
  --seed-headings "Indebtedness,Limitation on Indebtedness,Debt" \
  --article-range 6-8 \
  --sample 500 \
  --with-canonical-summary
```

## 5) Family-Level Baseline

```bash
python3 scripts/pattern_tester.py \
  --db "$DB" \
  --strategy "$STRAT_DIR/debt_capacity.indebtedness.general_basket_v001.json" \
  --sample 500

python3 scripts/coverage_reporter.py \
  --db "$DB" \
  --strategy "$STRAT_DIR/debt_capacity.indebtedness.general_basket_v001.json" \
  --group-by template_family \
  --sample 500
```

Target: L1 family hit rate >80%, stable across >=3 template families.

## 6) Child Drill-Down (L2)

Start with:

- `debt_capacity.indebtedness.general_basket`
- `debt_capacity.indebtedness.ratio_debt`
- `debt_capacity.indebtedness.incremental_equivalent`
- `debt_capacity.indebtedness.acquisition_debt`
- `debt_capacity.indebtedness.contribution_debt`

Use `section_reader.py --auto-unroll`, `child_locator.py --auto-unroll`,
`definition_finder.py`, and `dna_discoverer.py` to refine each strategy.

## 7) Persist + Evidence

```bash
python3 scripts/evidence_collector.py \
  --matches matches.json \
  --concept-id debt_capacity.indebtedness.general_basket \
  --workspace "$WS"

python3 scripts/strategy_writer.py \
  --db "$DB" \
  --concept-id debt_capacity.indebtedness.general_basket \
  --workspace "$WS" \
  --strategy updated_strategy.json \
  --note "Stage2 pilot refinement"
```

Circuit breaker must remain green for previously solved template groups.

## 8) Stage 2 Exit Criteria

- L1 (`debt_capacity.indebtedness`) hit rate >80%.
- At least 5 L2 children >50% hit rate.
- Gold-set precision >75% on non-holdout docs.
- Evidence JSONL rows use valid ontology `id` values in `ontology_node_id`.
