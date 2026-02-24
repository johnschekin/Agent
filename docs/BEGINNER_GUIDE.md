# Beginner Guide: Agent Ontology Discovery System

This guide explains what this system does, how to run it, and how to read results.

If you are planning implementation work, start from:
- `plans/master_rollout_plan.md`
- `plans/master_execution_backlog_p0_p2.md`

## 1) What This Project Is

The project discovers repeatable text/structure patterns in credit agreements, then links those patterns to ontology nodes.

Output goal:
- `ontology_node_id -> clause` mappings
- at scale (thousands of agreements)
- without calling an LLM for every document

Core idea:
- Use deterministic pattern discovery (headings, keywords, DNA phrases, structural position)
- Store parse results in DuckDB
- Iterate strategy files per concept family

## 2) Mental Model (Simple)

Think in 4 layers:

1. Corpus layer
- Raw agreements and sidecar metadata
- Parsed into sections, clauses, definitions

2. Ontology layer
- 3,538 nodes, grouped under 49 families (inside 6 domains)
- Node IDs are canonical keys (for example: `debt_capacity.indebtedness`)

3. Strategy layer
- A strategy tells the system how to find a concept in text
- Includes heading patterns, keyword anchors, DNA phrases, and structural hints

4. Discovery loop
- Hypothesize strategy
- Test on corpus
- Analyze misses
- Refine
- Persist strategy + evidence

## 3) Repo Layout You Should Know

- `src/agent/` core library (parsing, strategy model, corpus API)
- `scripts/` CLI tools used by humans/agents
- `data/ontology/` production ontology JSON
- `data/bootstrap/` bootstrap strategy seeds
- `workspaces/{family}/` per-family working area
- `plans/` target plans and execution reports

## 4) Key Terms

- `ontology_node_id`: Stable concept ID from ontology JSON.
- `family`: A top-level concept family (for example `debt_capacity.indebtedness`).
- `section`: Agreement section (like `6.01`).
- `clause`: Nested clause within section (`(a)`, `(i)`, etc.).
- `cohort_included`: Document passes leveraged credit-agreement filters.
- `template_family`: Cluster label from template classifier (`cluster_XXX` or `noise`).

## 5) How Discovery Works with the Ontology

1. Choose one ontology family (pilot uses `debt_capacity.indebtedness`).
2. Create a workspace with ontology subtree + bootstrap context.
3. Run discovery tools to learn where that family appears:
- common headings
- common structural locations (article/section)
- pattern hit rates
4. Save strategy updates with versioning.
5. Record evidence as provenance-grounded matches.
6. Produce labeled rows keyed by `ontology_node_id`.

Important:
- Every saved strategy/evidence row must reference valid ontology node IDs.

## 6) Typical Pilot Workflow (What You Run)

From `Agent/`:

```bash
export PYTHONPATH=src
export DB=/tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb
export WS=workspaces/indebtedness
```

Initialize workspace:

```bash
python3 scripts/setup_workspace.py \
  --family indebtedness \
  --expert-materials ~/Projects/TermIntelligence/analysis/indebtedness \
  --ontology data/ontology/r36a_production_ontology_v2.5.1.json \
  --bootstrap data/bootstrap/bootstrap_all.json \
  --output "$WS"
```

Build a gold-doc slice:

```bash
python3 scripts/sample_selector.py \
  --db "$DB" --n 50 --stratify template_family --seed 42 \
  --output "$WS/results/gold_docs.txt"
```

Map structure:

```bash
python3 scripts/structural_mapper.py \
  --db "$DB" \
  --concept indebtedness \
  --heading-patterns "Indebtedness,Limitation on Indebtedness,Debt" \
  --keyword-anchors "incur,incurrence,Permitted Indebtedness,Disqualified Stock" \
  --sample 500
```

Discover headings:

```bash
python3 scripts/heading_discoverer.py \
  --db "$DB" \
  --seed-headings "Indebtedness,Limitation on Indebtedness,Debt" \
  --article-range 6-8 \
  --sample 500 \
  --with-canonical-summary
```

Test strategy and coverage:

```bash
python3 scripts/pattern_tester.py \
  --db "$DB" \
  --strategy "$WS/results/indebtedness_family_strategy_v0.json" \
  --sample 500 --verbose

python3 scripts/coverage_reporter.py \
  --db "$DB" \
  --strategy "$WS/results/indebtedness_family_strategy_v0.json" \
  --group-by template_family
```

## 7) How to Start Manual Labeling

File to label:
- `workspaces/indebtedness/results/gold_set.jsonl`

Each row includes:
- `doc_id`
- `ontology_node_id`
- suggested `section_number`
- suggested score/method
- `split` (`eval` or `holdout`)
- `label_status` (currently `todo`)

Labeling process:
1. Open one row.
2. Verify if suggested section truly expresses the concept.
3. Fill/adjust:
- `section_number`
- `clause_path` (if known)
- `present` true/false
- optional `notes`
4. Set `label_status` from `todo` to your chosen done marker.

## 8) How to Read Pilot Outputs

- `pattern_tester_*.json`
  - Main metric: `hit_rate`
  - Check `miss_summary` for why misses happen

- `coverage_reporter_*.json`
  - Main metric: hit rate by `template_family`
  - Look for clusters with low or zero coverage

- `structural_mapper_*.json`
  - Shows where concept usually lives (article/section distributions)

- `heading_discoverer_*.json`
  - Lists observed heading variants
  - optional canonical concept hints

## 9) Current Pilot Snapshot (Local Full Run)

From latest full-local run (`full_3411.duckdb`):
- docs: `3411`
- cohort docs: `2834`
- family sample hit rate: `0.984` on sample-500
- all-cohort coverage: `0.9915`
- known blind spot: `cluster_039` has `section_count=0` for its docs (parser issue)

## 10) Common Beginner Mistakes

- Using a strategy JSON that is not in the `Strategy` dataclass format.
- Treating section-level hit as clause-level truth.
- Ignoring template-level blind spots because overall hit rate looks high.
- Editing `gold_set.jsonl` without preserving valid `ontology_node_id`.
- Running tools against a DB while another process still holds a write lock.

## 11) What to Do Next

After first pass:
1. Fix parser failures for zero-section template clusters.
2. Expand from family-level concept to child concepts using `child_locator.py`.
3. Save refined strategies with `strategy_writer.py`.
4. Collect evidence with `evidence_collector.py`.

For deeper plan context:
- `plans/final_target_vision.md`
- `plans/pilot_protocol.md`
- `~/.claude/plans/snuggly-meandering-lagoon.md`

Companion docs:
- `docs/architecture_diagram.md` (one-page visual architecture)
- `docs/ARCHITECTURE.md` (full architecture + roadmap)
- `docs/DAY1_ONBOARDING_CHECKLIST.md` (copy/paste Day 1 runbook)
