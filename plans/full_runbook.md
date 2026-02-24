# Full-Corpus Orchestration Runbook (Current Full Corpus: 12,583 Docs)

This runbook standardizes production corpus builds and downstream export artifacts.

Current baseline:
- Canonical full corpus snapshot size is **12,583 documents**.
- Use this runbook for full-corpus rebuilds and refresh cycles when new filings are ingested.

## 1. Preconditions

- Repo root: `Projects/Agent`
- AWS credentials configured for `us-east-1`
- Bucket access:
  - `s3://edgar-pipeline-documents-216213517387/documents/`
  - `s3://edgar-pipeline-documents-216213517387/metadata/`
- Ray cluster config present: `ray-cluster.yaml`
- Python deps installed (including `duckdb`, `pyarrow`, `scikit-learn`)

Quick checks:

```bash
aws s3 ls s3://edgar-pipeline-documents-216213517387/ | head
python3 scripts/check_corpus_v2.py --help
```

## 2. Build Modes

Use one of two approved production paths:

1. Preferred (`v2`, Parquet-sharded merge): `scripts/build_corpus_ray_v2.py`
2. Legacy (`v1`, actor writer): `scripts/build_corpus_ray.py` (only when needed for parity/debug)

## 3. Cluster Bring-Up

```bash
ray up ray-cluster.yaml
ray status
```

If running on single-node high-CPU local EC2, use `--local` mode in the build script.

## 4. Corpus Build (Production)

```bash
ray submit ray-cluster.yaml scripts/build_corpus_ray_v2.py -- \
  --bucket edgar-pipeline-documents-216213517387 \
  --output /home/ubuntu/corpus_index/corpus.duckdb \
  --s3-upload s3://edgar-pipeline-documents-216213517387/corpus_index/corpus.duckdb \
  --force -v
```

Expected artifacts on node:

- `/home/ubuntu/corpus_index/corpus.duckdb`
- `/home/ubuntu/corpus_index/corpus.run_manifest.json`

## 5. Post-Build Validation

```bash
python3 scripts/check_corpus_v2.py \
  --db /home/ubuntu/corpus_index/corpus.duckdb \
  --expected-schema 0.2.0

python3 scripts/corpus_profiler.py \
  --db /home/ubuntu/corpus_index/corpus.duckdb \
  --output /home/ubuntu/corpus_index/corpus_profile.json
```

Minimum checks:

- schema version matches expected
- non-zero rows in `documents`, `sections`, `clauses`, `definitions`
- parse anomaly report reviewed for blind spots

## 6. Template Classification

```bash
python3 scripts/template_classifier.py \
  --db /home/ubuntu/corpus_index/corpus.duckdb \
  --output /home/ubuntu/corpus_index/templates/classifications.json \
  --profile pilot_balanced \
  --fail-on-gate
```

Review `classification_report.json`:

- cluster count gate
- non-noise coverage gate
- noise-rate gate
- mean-confidence gate

## 7. Pilot Family Validation

```bash
python3 scripts/pattern_tester.py --db /home/ubuntu/corpus_index/corpus.duckdb --strategy workspaces/indebtedness/strategies/current.json --sample 500
python3 scripts/coverage_reporter.py --db /home/ubuntu/corpus_index/corpus.duckdb --strategy workspaces/indebtedness/strategies/current.json --group-by template_family --sample 500
```

Persist evidence:

```bash
python3 scripts/evidence_collector.py \
  --matches workspaces/indebtedness/results/latest_pattern_tester.json \
  --concept-id debt_capacity.indebtedness \
  --workspace workspaces/indebtedness

# Note: evidence_collector and strategy_writer both auto-update
# workspaces/<family>/checkpoint.json progression metadata.
```

## 8. Strategy Save (Release Candidate)

```bash
python3 scripts/llm_judge.py \
  --matches workspaces/indebtedness/results/latest_matches.json \
  --concept-id debt_capacity.indebtedness \
  --sample 20 \
  --output workspaces/indebtedness/results/judge/latest.json

python3 scripts/strategy_writer.py \
  --concept-id debt_capacity.indebtedness \
  --workspace workspaces/indebtedness \
  --strategy workspaces/indebtedness/strategies/proposed.json \
  --db /home/ubuntu/corpus_index/corpus.duckdb \
  --release-mode \
  --judge-report workspaces/indebtedness/results/judge/latest.json
```

## 9. Labeled Dataset Export

```bash
python3 scripts/export_labeled_data.py \
  --inputs workspaces/indebtedness/evidence \
  --output-prefix workspaces/indebtedness/results/labeled_data \
  --format both \
  --dedupe
```

Outputs:

- `*.jsonl`
- `*.parquet` (when pyarrow available)

## 10. Swarm Wave Dispatch

Prepare full-family assets (one-time per ontology version):

```bash
python3 scripts/setup_workspaces_all.py \
  --ontology data/ontology/r36a_production_ontology_v2.5.1.json \
  --bootstrap data/bootstrap/bootstrap_all.json \
  --workspace-root workspaces \
  --dry-run \
  --summary-out plans/setup_workspaces_all_dry_run_$(date +%F).json

python3 scripts/generate_swarm_conf.py \
  --ontology data/ontology/r36a_production_ontology_v2.5.1.json \
  --output swarm/swarm.full49.conf \
  --wave1-count 5 \
  --backend opus46 \
  --panes 4 \
  --force
```

Use subtree whitelist entries (`family_id.*`) in swarm assignments to keep
`strategy_writer.py` gating strict without enumerating every descendant concept.

Launch and dispatch:

```bash
./swarm/launch.sh --session agent-swarm --panes 4
SWARM_CONF=swarm/swarm.full49.conf ./swarm/dispatch-wave.sh 1 --session agent-swarm
./swarm/status.sh --session agent-swarm

python3 scripts/swarm_run_ledger.py \
  --conf swarm/swarm.full49.conf \
  --workspace-root workspaces \
  --session agent-swarm \
  --wave 1 \
  --stale-minutes 120 \
  --output plans/wave1_swarm_ledger_$(date +%F).json \
  --append-jsonl plans/swarm_run_ledger_history.jsonl

python3 scripts/swarm_watchdog.py \
  --conf swarm/swarm.full49.conf \
  --workspace-root workspaces \
  --wave 1 \
  --stale-minutes 90 \
  --bootstrap-grace-minutes 20 \
  --check-pane-activity \
  --session agent-swarm \
  --fail-on critical \
  --output plans/wave1_watchdog_$(date +%F).json \
  --append-jsonl plans/swarm_watchdog_history.jsonl

python3 scripts/swarm_artifact_manifest.py \
  --conf swarm/swarm.full49.conf \
  --workspace-root workspaces \
  --wave 1 \
  --output plans/wave1_artifact_manifest_$(date +%F).json \
  --append-jsonl plans/swarm_artifact_manifest_history.jsonl

# Consolidated snapshot (ledger + watchdog + manifest + optional transition gate)
python3 scripts/swarm_ops_snapshot.py \
  --conf swarm/swarm.full49.conf \
  --workspace-root workspaces \
  --session agent-swarm \
  --wave 1 \
  --next-wave 2 \
  --watchdog-check-pane-activity \
  --plans-dir plans \
  --output plans/wave1_ops_snapshot_$(date +%F).json \
  --append-jsonl plans/swarm_ops_snapshot_history.jsonl
```

Before dispatching Wave 2+, evaluate prior-wave completion gate:

```bash
python3 scripts/wave_transition_gate.py \
  --conf swarm/swarm.full49.conf \
  --workspace-root workspaces \
  --target-wave 2 \
  --scope previous \
  --output plans/wave2_transition_gate_$(date +%F).json
```

`swarm/dispatch-wave.sh` now enforces this gate by default for wave > 1.
Use `--waiver-file` for explicit documented exceptions, or
`--skip-transition-gate` for emergency/manual override.

Promote completed wave checkpoints once artifact criteria are met:

```bash
python3 scripts/wave_promote_status.py \
  --conf swarm/swarm.full49.conf \
  --workspace-root workspaces \
  --wave 1 \
  --from-statuses running \
  --to-status completed \
  --require-strategy \
  --require-evidence \
  --min-strategy-files 1 \
  --min-evidence-files 1 \
  --min-evidence-records 1 \
  --note "wave1-bootstrap-evidence-complete" \
  --output plans/wave1_status_promotion_$(date +%F).json
```

Wave-2 readiness planning and dispatch dry-run:

```bash
python3 scripts/wave_scheduler.py \
  --conf swarm/swarm.full49.conf \
  --workspace-root workspaces \
  --mode ready \
  --wave 2 \
  --families-out plans/wave2_ready_families_$(date +%F).txt \
  > plans/wave2_ready_$(date +%F).json

SWARM_CONF=swarm/swarm.full49.conf ./swarm/dispatch-wave.sh 2 --session agent-swarm --dry-run \
  > plans/wave2_dispatch_dry_run_$(date +%F).txt
```

Queue-safe dispatch for waves that map many families to the same pane
(for example, Wave-3 on `swarm.full49.conf`):

```bash
# Start at most one family per pane for this dispatch cycle (default behavior).
SWARM_CONF=swarm/swarm.full49.conf ./swarm/dispatch-wave.sh 3 --session agent-swarm

# Optional explicit cap (same as default):
SWARM_CONF=swarm/swarm.full49.conf ./swarm/dispatch-wave.sh 3 --session agent-swarm \
  --max-starts-per-pane 1

# Do NOT restart running families unless explicitly requested:
# --force-restart bypasses running/pane-busy protection.
SWARM_CONF=swarm/swarm.full49.conf ./swarm/dispatch-wave.sh 3 --session agent-swarm \
  --force-restart
```

Operational cadence for multi-family waves:
1. Dispatch one batch (`<= panes` families).
2. Persist strategy/evidence and promote completed families via `wave_promote_status.py`.
3. Re-run dispatch for the same wave to launch the next tranche.

Failed-only rerun:

```bash
SWARM_CONF=swarm/swarm.full49.conf ./swarm/dispatch-wave.sh 1 --session agent-swarm --failed-only
```

Dependency planning:

```bash
python3 scripts/wave_scheduler.py --conf swarm/swarm.full49.conf --workspace-root workspaces --mode ready --wave 1
```

## 11. Teardown

```bash
ray down ray-cluster.yaml -y
```

## 12. Required Artifacts Per Full Run

- `corpus.duckdb`
- `corpus.run_manifest.json`
- `corpus_profile.json`
- `templates/classifications.json`
- `templates/classification_report.json`
- family-level strategy/evidence/judge outputs
- labeled export files (JSONL/Parquet)
