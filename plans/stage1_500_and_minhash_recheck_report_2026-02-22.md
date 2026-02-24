# MinHash Re-Check + Stage 1 (500 Docs) Pipeline Report (2026-02-22)

## 1) `datasketch` install + re-check on existing 300-doc DB
- Install target: `/tmp/agent_stage15_deps`
- Default MinHash run: `clusters=0`, `noise_docs=230`, `documents=230`, `coverage=0.00%`
- Focused parameter sweep executed (`45` configs).
- Best config: `eps=0.4`, `min_samples=2`, `lsh_threshold=0.2`
- Tuned MinHash rerun: `clusters=9`, `noise_docs=202`, `documents=230`, `coverage=12.17%`
- `>=5 clusters` gate re-check: **PASS**
- Note: tuned config passes cluster-count gate but remains high-noise.

## 2) Same pipeline at 500 docs (Stage 1 gate run)
- Sample source: TermIntelligence real agreements + sidecars
- Sample size: `500`
- Built DB: `/tmp/agent_stage1_run_500/corpus_index/stage1_500.duckdb`
- Build time (`8` workers): `167.42s`
- Post-build sequence executed: template classifier, corpus profiler, and same 13-tool command sequence.
- Tool execution status: `13/13` passed

### Stage 1 Non-Dashboard Gates
- Pass: **7**
- Fail: **0**

| Gate | Target | Actual | Status |
|---|---|---|---|
| `docs_500_min` | >=500 | 500 | **PASS** |
| `cohort_policy` | 0 violations | 0 | **PASS** |
| `section_success` | >0.90 | 0.9867 | **PASS** |
| `definition_success` | >0.80 | 1.0000 | **PASS** |
| `borrower_populated` | >0.70 | 1.0000 | **PASS** |
| `doc_type_classified` | >0.90 not other | 0.9980 | **PASS** |
| `tools_13_smoke` | 13/13 pass | {"ok": 13, "total": 13} | **PASS** |

### Key 500-doc Metrics
- Cohort docs: `377`
- Cohort section success: `98.67%`
- Cohort definition success: `100.00%`
- Cohort borrower populated: `100.00%`
- Doc type classified (not `other`): `99.80%`
- Cohort policy violations: `0`
- Excluded by doc_type: `{"credit_agreement": 117, "amendment": 5, "other": 1}`
- Excluded credit agreements by segment: `{"uncertain": 117}`

### Template classifier behavior on 500-doc run (default settings)
- Distinct clusters: `0`
- Non-noise cluster coverage: `0.00%`
- This run intentionally used the same default command sequence (no tuned MinHash params).

## Artifacts
- 300-doc re-check JSON: `/tmp/agent_stage15_dryrun/run/minhash_recheck_300.json`
- 300-doc tuned classifications: `/tmp/agent_stage15_dryrun/corpus_index/templates/classifications_minhash_tuned.json`
- 500-doc gate JSON: `/tmp/agent_stage1_run_500/run/stage1_500_gate_report.json`
- 500-doc tool run summary: `/tmp/agent_stage1_run_500/run/tool_run_summary.json`
- 500-doc profile: `/tmp/agent_stage1_run_500/corpus_index/corpus_profile.json`
- 500-doc build stderr (timing): `/tmp/agent_stage1_run_500/run_build.stderr.txt`
