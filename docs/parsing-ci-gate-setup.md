# Parsing CI Gate Setup

This repo now includes a parser-quality gate runner and a GitHub Actions workflow.

## Files
- `scripts/parsing_ci_gate.py`
- `scripts/replay_gold_fixtures.py`
- `scripts/build_replay_smoke_pack.py`
- `config/parsing_ci_gate_thresholds.json`
- `config/gold_replay_gate_thresholds.json`
- `data/fixtures/gold/v1/gates/replay_smoke_v1.jsonl`
- `.github/workflows/parsing-ci-gate.yml`

## Local Usage

Quick gate (no corpus DB required):

```bash
python3 scripts/parsing_ci_gate.py --mode quick --report artifacts/parsing_ci_gate_quick.json
```

Direct replay gate run:

```bash
python3 scripts/replay_gold_fixtures.py \
  --fixtures data/fixtures/gold/v1/gates/replay_smoke_v1.jsonl \
  --thresholds config/gold_replay_gate_thresholds.json \
  --json
```

Full gate (requires local corpus DB):

```bash
python3 scripts/parsing_ci_gate.py \
  --mode full \
  --db corpus_index/corpus.duckdb \
  --collision-baseline data/quality/edge_case_clause_guardrail_baseline.json \
  --parent-baseline data/quality/edge_case_clause_parent_guardrail_baseline.json \
  --thresholds config/parsing_ci_gate_thresholds.json \
  --report artifacts/parsing_ci_gate_full.json
```

## GitHub Actions

### Quick gate
Runs on every `pull_request` and `push` using GitHub-hosted runner (`ubuntu-latest`).

### Full gate
Manual run only (`workflow_dispatch`) and configured for a `self-hosted` runner.

Requirements for full gate runner:
- `corpus_index/corpus.duckdb` present in workspace
- baseline files present:
  - `data/quality/edge_case_clause_guardrail_baseline.json`
  - `data/quality/edge_case_clause_parent_guardrail_baseline.json`

## Notes
- Quick gate is the default CI protection.
- Full gate is the release-grade dataset-aware gate.
- Thresholds are centrally managed in `config/parsing_ci_gate_thresholds.json`.
