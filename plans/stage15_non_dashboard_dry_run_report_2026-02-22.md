# Stage 1 + 1.5 Non-Dashboard Dry-Run Report (2026-02-22)

## Scope
- Real sample: 300 agreements from `TermIntelligence/data/credit_agreements` + matching sidecars from `TermIntelligence/data/sidecar_metadata`
- Build/index target: `/tmp/agent_stage15_dryrun/corpus_index/stage15_sample.duckdb`
- Tool execution: all 13 non-dashboard Stage 1.5 tools against this index

## Topline
- Total docs: **300**
- Cohort docs: **230**
- Sections success (cohort): **99.13%**
- Definitions success (cohort): **100.00%**
- Borrower populated (cohort): **100.00%**
- Tool runs: **13/13 passed**
- Timed build (300 docs, 8 workers): **96.04s**

## Gate Summary
- Pass: **11**
- Fail: **3**
- N/A: **0**

| Gate | Target | Actual | Status |
|---|---|---|---|
| `stage1_docs_500_min` | documents >= 500 | 300 | **FAIL** |
| `stage1_cohort_policy` | cohort flags only leveraged credit agreements at medium+ confidence | 0 | **PASS** |
| `stage1_section_success` | > 90% cohort docs with >=1 section | 0.9913 | **PASS** |
| `stage1_definition_success` | > 80% cohort docs with >=1 definition | 1.0000 | **PASS** |
| `stage1_borrower_populated` | > 70% cohort docs with borrower | 1.0000 | **PASS** |
| `stage1_doc_type_classified` | > 90% documents not classified as other | 1.0000 | **PASS** |
| `stage1_tools_13_smoke` | 13/13 tool runs succeed | {"ok": 13, "total": 13} | **PASS** |
| `stage1_setup_workspace_ontology_id_validation` | setup_workspace uses and validates ontology ids | validated in run + tests/test_setup_workspace.py | **PASS** |
| `stage1_5_docs_25000_min` | documents >= 25,000 | 300 | **FAIL** |
| `stage1_5_template_assign_gt_80pct` | > 80% cohort docs assigned to non-noise cluster | 0.8217 | **PASS** |
| `stage1_5_template_clusters_ge_5` | >= 5 distinct template clusters | 1 | **FAIL** |
| `stage1_5_dna_candidates_ge_10` | >= 10 passed DNA candidates for indebtedness | 30 | **PASS** |
| `stage1_5_profile_generated` | corpus_profile.json generated | True | **PASS** |
| `stage1_5_build_under_2h` | build time < 2 hours | 96.0400 | **PASS** |

## Failures To Address
- `stage1_docs_500_min`: sample size was 300 (dry-run scope).
- `stage1_5_docs_25000_min`: full-corpus ingestion not executed in this dry-run.
- `stage1_5_template_clusters_ge_5`: only 1 non-noise cluster discovered on this run.

## Key Diagnostics
- Template classification coverage (>80% gate): 189/230 = 82.17% (PASS)
- Template distinct clusters gate failed due low cluster diversity on this sample run.
- `template_classifier.py` logged fallback to TF-IDF because `datasketch` is not installed, so MinHash+LSH path was not exercised.
- Excluded docs by doc_type: {"credit_agreement": 69, "amendment": 1}
- Excluded credit agreements by segment: {"uncertain": 69}

## Artifacts
- Dry-run root: `/tmp/agent_stage15_dryrun`
- Gate JSON: `/tmp/agent_stage15_dryrun/run/stage15_non_dashboard_gate_report.json`
- Tool summary: `/tmp/agent_stage15_dryrun/run/tool_run_summary.json`
- Corpus profile: `/tmp/agent_stage15_dryrun/corpus_index/corpus_profile.json`
- Template classifications: `/tmp/agent_stage15_dryrun/corpus_index/templates/classifications.json`
- Timed build stderr (includes `real/user/sys`): `/tmp/agent_stage15_dryrun/run/build_timed.stderr.txt`
