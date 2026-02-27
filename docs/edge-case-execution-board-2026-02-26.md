# Edge Case Parsing Quality Execution Board
Date: 2026-02-26  
Depends on: `docs/edge-case-root-cause-analysis-2026-02-26.md`, `docs/edge-case-remediation-plan-2026-02-26.md`

## Objective
Drive parser-integrity defects to low, controlled levels while preserving ontology-linking correctness at section, clause, and defined-term granularity.

## Baseline (from RCA)
- Corpus docs: 3,298
- High-impact parser categories:
  - `missing_sections`: 194 docs
  - `zero_definitions`: 187 docs
  - `definition_truncated_at_cap`: 329 docs
  - `definition_signature_leak`: 36 docs
  - `clause_dup_id_burst`: 46 docs
  - `clause_root_label_repeat_explosion`: 32 docs
  - `clause_depth_reset_after_deep`: 8 docs

## Owner Lanes
- `PARSER`: section + clause parsing core (`src/agent/doc_parser.py`, `src/agent/clause_parser.py`)
- `EXTRACT`: definition extraction + boundaries (`src/agent/doc_parser.py`, `src/agent/definitions.py`, `src/agent/document_processor.py`)
- `EDGE`: edge-case detector/query framework (`dashboard/api/server.py`, `tests/test_edge_cases.py`)
- `LINK`: ontology-link payload fidelity (`dashboard/api/server.py`, `scripts/link_worker.py`, `src/agent/link_store.py`)
- `UI`: edge-case and review/query UX validation (`dashboard/src/app/edge-cases/page.tsx`, `dashboard/src/components/edge-cases/*`)
- `QA`: fixtures, guardrails, runbook, release gates (`tests/*`, `scripts/edge_case_clause_guardrail.py`, `data/quality/*`)

## Release Gates
- `Gate A` Parser integrity: no regression in clause collision guardrail.
- `Gate A2` Parent-link integrity: no regression in x/y parent-loss guardrail.
- `Gate B` Definition integrity: no capped definitions in gold fixtures; signature leakage below threshold.
- `Gate C` Linking integrity: clause path + defined-term span persisted and rendered correctly in review/query previews.
- `Gate D` Operational integrity: detector status coverage is explicit (`active`/`monitor-only`/`retired`) with no silent dead checks.

## P1 Board (Blocking Parser/Extractor Fixes)
| Ticket | Lane | Root Cause | Primary Files | Deliverable | Validation | Exit Criteria |
|---|---|---|---|---|---|---|
| EC-P1-01 Section Parse Recovery | PARSER | Section parser hard failures causing missing sections/definitions | `src/agent/doc_parser.py`, `src/agent/section_parser.py`, `src/agent/document_processor.py`, `tests/test_doc_parser.py`, `tests/test_zero_section_recovery.py` | Fallback heading recognizers + parser mode trace on failed docs | `pytest -q tests/test_doc_parser.py tests/test_zero_section_recovery.py -p no:cacheprovider` | `missing_sections` and `zero_definitions` each reduced by >=75% from baseline |
| EC-P1-02 Clause Path Canonicalization | PARSER | `_dup` cascades and unstable clause paths | `src/agent/clause_parser.py`, `src/agent/doc_parser.py`, `src/agent/document_processor.py`, `tests/test_clause_parser.py`, `tests/test_edge_cases.py` | Canonical path reconstruction, raw-node audit retained separately | `pytest -q tests/test_clause_parser.py tests/test_edge_cases.py -p no:cacheprovider` + guardrail script | `clause_dup_id_burst` <10 docs, `root_label_repeat_explosion` <8 docs |
| EC-P1-03 Full Definition Span Storage | EXTRACT | 2000-char definition cap clipping legal definitions | `src/agent/definitions.py`, `src/agent/doc_parser.py`, `src/agent/corpus.py`, `tests/test_definitions.py`, `tests/test_edge_cases.py` | Remove hard cap, preserve full definition text and offsets | `pytest -q tests/test_definitions.py tests/test_edge_cases.py -p no:cacheprovider` | `definition_truncated_at_cap` near zero and long-term fixtures complete |
| EC-P1-04 Signature-Page Boundary Exclusion | EXTRACT | Signature text leaking into definitions | `src/agent/doc_parser.py`, `src/agent/metadata.py`, `tests/test_doc_parser.py`, `tests/test_edge_cases.py` | Signature boundary guard + exclusion heuristics | same as above | `definition_signature_leak` <5 docs with no material false suppression |
| EC-P1-05 Linking Payload Fidelity | LINK | Parsed spans not consistently flowing to stored links and preview rendering | `dashboard/api/server.py`, `scripts/link_worker.py`, `src/agent/link_store.py`, `tests/test_link_worker.py`, `tests/test_bulk_family_linker.py` | Stable clause/defined-term identifiers + span persistence in `family_links` | `pytest -q tests/test_link_worker.py tests/test_bulk_family_linker.py -p no:cacheprovider` | Review/query open directly to correct clause/term with correct highlight |

## P2 Board (Detector Calibration + Signal Quality)
| Ticket | Lane | Root Cause | Primary Files | Deliverable | Validation | Exit Criteria |
|---|---|---|---|---|---|---|
| EC-P2-01 Detector Status Hardening | EDGE | Dormant checks from logic drift | `dashboard/api/server.py`, `tests/test_edge_cases.py` | All detectors tagged active/monitor-only/retired + rationale | `pytest -q tests/test_edge_cases.py -p no:cacheprovider` | No detector category silently dead |
| EC-P2-02 Numbering Gap Logic Recalibration | EDGE | Dot-number format mismatch in section numbering gap | `dashboard/api/server.py`, `tests/test_edge_cases.py` | Correct gap detection for mixed numbering styles | same | `section_numbering_gap` produces meaningful results on synthetic fixtures |
| EC-P2-03 Malformed Term Detector Correctness | EDGE | Regex/escaping drift in malformed term check | `dashboard/api/server.py`, `tests/test_edge_cases.py` | Reliable malformed-term detection on newline/control-char cases | same | Detector behavior matches fixture expectations |
| EC-P2-04 Duplicate Definition (Normalized) | EDGE | Exact-match duplicate detector missing normalized duplicates | `dashboard/api/server.py`, `tests/test_edge_cases.py` | Add normalized duplicate detector (case/punct/space normalized) | same | New detector has actionable precision on sampled docs |
| EC-P2-05 Threshold Rebalance for Low Definitions | EDGE | Over-dominant `low_definitions` category | `dashboard/api/server.py`, `tests/test_edge_cases.py` | Cohort-aware thresholding or percentile calibration | same | Parser-integrity queue is no longer dominated by low_definitions noise |
| EC-P2-06 Monitoring Channel Split | UI + EDGE | Outlier-only categories mixed with parser defects | `dashboard/api/server.py`, `dashboard/src/app/edge-cases/page.tsx`, `tests/test_edge_cases.py` | Clear parser-integrity default queue + monitor channel toggle | `pytest -q tests/test_edge_cases.py -p no:cacheprovider` + `cd dashboard && npx tsc --noEmit` | Triage list prioritizes fixable parser defects |

## P3 Board (Operational Hardening + Rollout)
| Ticket | Lane | Root Cause | Primary Files | Deliverable | Validation | Exit Criteria |
|---|---|---|---|---|---|---|
| EC-P3-01 CI Guardrail Integration | QA | Guardrail exists but may not run consistently in release path | `scripts/edge_case_clause_guardrail.py`, `data/quality/edge_case_clause_guardrail_baseline.json`, CI workflow files | Enforced guardrail step before merge/release | run guardrail command in CI and local | Any clause-collision regression blocks merge |
| EC-P3-02 Gold Fixture Bank Expansion | QA | Missing representative fixtures for known parser failures | `tests/fixtures/*`, `tests/test_doc_parser.py`, `tests/test_clause_parser.py`, `tests/test_edge_cases.py` | Fixture set for long definitions, deep clause trees, signature-heavy tails, non-standard headings | full parser-focused pytest subset | All prior known failures are represented and locked |
| EC-P3-03 Corpus Backfill + Delta Report | QA + EDGE | Need measurable before/after impact and rollback visibility | `scripts/*`, `dashboard/api/server.py`, docs runbook | Repeatable backfill command + delta metrics report by category | backfill run + edge-case API snapshots | Signed-off quality delta report for each parser release |
| EC-P3-04 Review/Query Acceptance Checklist | UI + LINK | Parser fixes must be visibly correct in analyst workflow | `dashboard/src/app/links/page.tsx`, `dashboard/api/server.py`, e2e tests | Manual+automated acceptance checks for row-open navigation/highlighting | `npx playwright test` targeted suites (if available) | Analyst can validate clause/term link correctness pre-publish |

## Test Matrix (Minimum per PR)
1. Parser core changes:
   - `pytest -q tests/test_doc_parser.py tests/test_clause_parser.py tests/test_zero_section_recovery.py -p no:cacheprovider`
2. Edge-case detector changes:
   - `pytest -q tests/test_edge_cases.py tests/test_edge_case_clause_guardrail.py tests/test_edge_case_clause_parent_guardrail.py -p no:cacheprovider`
   - `python3 scripts/edge_case_clause_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_guardrail_baseline.json`
   - `python3 scripts/edge_case_clause_parent_guardrail.py --db corpus_index/corpus.duckdb --baseline data/quality/edge_case_clause_parent_guardrail_baseline.json`
3. Linking payload changes:
   - `pytest -q tests/test_link_worker.py tests/test_bulk_family_linker.py -p no:cacheprovider`
4. Frontend edge-case UI changes:
   - `cd dashboard && npx tsc --noEmit`

## Milestone Plan
- `M1 (P1 complete)`: parser/extractor correctness restored on critical defects; no major clipping/collision failures.
- `M2 (P2 complete)`: detector suite calibrated; parser-integrity queue clean and high-signal.
- `M3 (P3 complete)`: guardrails fully operational; release process enforces non-regression.

## Risks and Mitigations
- Risk: false positives from aggressive signature exclusion.
  - Mitigation: require fixture pass + sampled manual review for top impacted terms.
- Risk: canonical clause-path rewrite breaks historical references.
  - Mitigation: persist raw parse IDs for audit; migrate link resolution with backward-compatible fallback.
- Risk: threshold tuning hides true defects.
  - Mitigation: dual reporting period with old and new detector outputs.

## Workboard Status Template
Use this per ticket:
- Status: `todo | in_progress | blocked | review | done`
- Owner:
- PR(s):
- Baseline metric:
- Current metric:
- Notes:
