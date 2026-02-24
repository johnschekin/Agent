# Release and Lineage Checklist

Use this checklist before publishing a labeled-data snapshot.

Current corpus baseline:
- Canonical full corpus size is **12,583 documents** (as of 2026-02-23).
- Treat this as the full-corpus denominator for rollout/release checks unless a newer manifest supersedes it.

## A. Build Integrity

- [ ] Corpus build completed from approved script (`build_corpus_ray_v2.py` preferred).
- [ ] `corpus.run_manifest.json` exists and is attached to release bundle.
- [ ] `check_corpus_v2.py` passed schema and table checks.
- [ ] `corpus_profiler.py` output reviewed for parse anomalies.

## B. Template and Coverage Quality

- [ ] `template_classifier.py` quality gates passed (`--fail-on-gate`).
- [ ] Template coverage spread reviewed (`coverage_reporter.py`).
- [ ] No major blind-spot template clusters remain unresolved.

## C. Strategy Quality Gates

- [ ] Regression gate passed in `strategy_writer.py`.
- [ ] Outlier policy gate passed.
- [ ] Did-not-find policy gate passed.
- [ ] Confidence policy gate passed (if enabled).
- [ ] Release-mode judge gate passed (`--release-mode --judge-report ...`).

## D. Swarm Governance

- [ ] Full-family swarm assignment file generated (`swarm/swarm.full49.conf`) and reviewed.
- [ ] Bulk workspace setup plan generated (`setup_workspaces_all.py` summary) and triaged.
- [ ] Family checkpoint states are consistent (`swarm/status.sh`).
- [ ] Swarm run ledger captured (`scripts/swarm_run_ledger.py`) and reviewed for stale-running families.
- [ ] Swarm watchdog run captured (`scripts/swarm_watchdog.py`) and critical alerts triaged.
- [ ] Family artifact manifest captured (`scripts/swarm_artifact_manifest.py`) and review-ready totals verified.
- [ ] Consolidated ops snapshot captured (`scripts/swarm_ops_snapshot.py`) with go/no-go decision archived.
- [ ] Wave transition gate evaluated for next wave (`scripts/wave_transition_gate.py`) with waivers documented if used.
- [ ] Wave lifecycle promotion captured (`scripts/wave_promote_status.py`) when moving families to `completed/locked`.
- [ ] Concept whitelist enforcement active (`AGENT_CONCEPT_WHITELIST` or `--concept-whitelist`).
- [ ] Out-of-scope discoveries logged and triaged.

## E. Dataset Export and Lineage

- [ ] `export_labeled_data.py` completed.
- [ ] JSONL export produced and schema-checked.
- [ ] Parquet export produced (or documented pyarrow limitation).
- [ ] Export includes lineage fields:
  - `export_run_id`
  - `source_db`
  - `source_db_manifest`
  - `source_evidence_file`
  - `source_run_id`
  - `source_strategy_version`

## F. Release Bundle Contents

- [ ] `corpus.duckdb`
- [ ] `corpus.run_manifest.json`
- [ ] `corpus_profile.json`
- [ ] `templates/classifications.json`
- [ ] `templates/classification_report.json`
- [ ] strategy versions (`*_vNNN.json`, `.raw.json`, `.resolved.json`)
- [ ] judge reports (`*_vNNN.judge.json` where applicable)
- [ ] evidence JSONL files
- [ ] labeled export files (`.jsonl`, `.parquet`)
- [ ] this checklist with sign-off metadata
- [ ] swarm run ledger artifact(s) (`plans/*swarm_ledger*.json` or JSONL history)
- [ ] swarm watchdog artifact(s) (`plans/*watchdog*.json` or JSONL history)
- [ ] swarm artifact manifest(s) (`plans/*artifact_manifest*.json` or JSONL history)
- [ ] wave status promotion artifact(s) (`plans/*status_promotion*.json`)

## G. Sign-Off

- [ ] Technical sign-off (pipeline owner)
- [ ] Domain sign-off (concept quality reviewer)
- [ ] Publish timestamp and release tag recorded
