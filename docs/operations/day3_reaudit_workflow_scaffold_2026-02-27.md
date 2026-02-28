# Day 3 Re-Audit Workflow Scaffold
Date: 2026-02-27
Run: `launch_run_2026-02-27_day3`

## Purpose
Provide deterministic scaffolding for Day 4+ 10% re-audit execution.

## Command
```bash
python3 scripts/build_reaudit_sample.py \
  --batch artifacts/launch_run_2026-02-27_day3/adjudication/manual_adjudication_batch_train40_rowsetB20.jsonl \
  --batch artifacts/launch_run_2026-02-27_day3/adjudication/manual_adjudication_batch_train40_rowsetC20.jsonl \
  --sample-ratio 0.10 \
  --min-sample-size 4 \
  --seed 20260227 \
  --out artifacts/launch_run_2026-02-27_day3/adjudication/manual_reaudit_sample_day3_scaffold.jsonl
```

## Output
1. `artifacts/launch_run_2026-02-27_day3/adjudication/manual_reaudit_sample_day3_scaffold.jsonl`
2. `artifacts/launch_run_2026-02-27_day3/adjudication/manual_reaudit_sample_day3_scaffold_summary.json`

## Notes
1. Output rows are templates and must be completed during the Day 4 re-audit pass.
2. Sampling is deterministic for a fixed seed and input batch set.
