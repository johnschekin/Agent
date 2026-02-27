# Parsing Baseline Freeze (2026-02-27)

This document freezes the parser-quality baseline prior to refactor phase 1.

## Snapshot Artifact
- `data/quality/parsing_baseline_freeze_2026-02-27.json`

## Source
- Commit anchor: `284ff54`
- Corpus DB: `corpus_index/corpus.duckdb`
- API scope: `/api/edge-cases?group=parser_integrity&cohort_only=true`

## Frozen Totals
- Parser integrity (`detector_status=all`): `17,397`
- Parser integrity (`detector_status=active`): `16,694`

## Referenced Guardrail Assets
- `data/quality/edge_case_clause_guardrail_baseline.json`
- `data/quality/edge_case_clause_parent_guardrail_baseline.json`
- `config/parsing_ci_gate_thresholds.json`

## Reproduce
```bash
python3 - <<'PY'
import asyncio
from agent.corpus import CorpusIndex
from dashboard.api import server

server._corpus = CorpusIndex('corpus_index/corpus.duckdb')
resp = asyncio.run(server.edge_cases(category='all', group='parser_integrity', detector_status='all', page=0, page_size=200, cohort_only=True))
print(resp['total'])
PY
```
