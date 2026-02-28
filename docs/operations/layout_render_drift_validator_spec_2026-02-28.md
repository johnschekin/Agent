# Layout Render Drift Validator Spec

Date:
1. 2026-02-28

Status:
1. Binding spec for deterministic HTML->PDF render checks used by layout-sidecar confidence flow.

## 1) Purpose
1. Ensure layout-derived ML confidence signals are reproducible.
2. Detect render nondeterminism before any model-sidecar decision is consumed.
3. Prevent false parser escalations caused by renderer/font/reflow drift.

## 2) Scope
1. Input is a single contract HTML (or a manifest of many HTML files).
2. Validator performs two controlled renders using a fixed profile.
3. Validator compares page text and token bounding boxes across repeats.
4. Validator emits pass/fail JSON report and deterministic evidence artifacts.

## 3) CLI Contract
Command:
1. `python3 scripts/validate_layout_render_drift.py --html <html_path> --profile config/layout_render_profile_v1.json --work-dir <artifact_dir> --json-out <artifact_dir>/layout_render_drift_report.json`

Batch variant:
1. `python3 scripts/validate_layout_render_drift.py --manifest <manifest_jsonl> --profile config/layout_render_profile_v1.json --work-dir <artifact_dir> --json-out <artifact_dir>/layout_render_drift_report.json`

Required arguments:
1. `--profile`: profile contract JSON (`layout-render-profile-v1`).
2. `--work-dir`: directory where render and extraction artifacts are written.
3. `--json-out`: output drift report path.
4. One of:
   1. `--html` for single file mode.
   2. `--manifest` for batch mode.

Optional arguments:
1. `--strict`: fail on warnings.
2. `--max-docs <N>`: cap batch size in one invocation.
3. `--keep-pdfs`: preserve both repeat PDFs (default true for forensic runs).
4. `--fail-fast`: stop after first critical failure.

Exit codes:
1. `0`: pass.
2. `2`: drift contract violation (nondeterminism over threshold, missing required artifact, policy fail).
3. `3`: invalid input/profile/schema.
4. `4`: internal validator/runtime error.

## 4) Inputs and Contracts
Profile requirements:
1. `schema_version` must be `layout-render-profile-v1`.
2. `status` must be `binding`.
3. `renderer.version_pinned` must be true.
4. Determinism thresholds must be present.

Single-file mode inputs:
1. HTML file path.
2. Optional metadata fields:
   1. `doc_id`
   2. `section_number` (when validating section-only snippets)

Manifest mode inputs:
1. JSONL rows with required fields:
   1. `doc_id`
   2. `html_path`
2. Optional fields:
   1. `section_number`
   2. `expected_page_count`
   3. `cohort`

## 5) Output Schema
`layout_render_drift_report.json` required top-level fields:
1. `schema_version` (`layout-render-drift-report-v1`)
2. `generated_at`
3. `validator_version`
4. `profile_path`
5. `profile_sha256`
6. `status` (`pass|fail|warn`)
7. `summary`:
   1. `docs_total`
   2. `docs_passed`
   3. `docs_failed`
   4. `checks_passed`
   5. `checks_failed`
8. `documents[]`:
   1. `doc_id`
   2. `html_path`
   3. `status`
   4. `checks[]` (see check schema below)
   5. `metrics`:
      1. `page_count_a`
      2. `page_count_b`
      3. `token_count_a`
      4. `token_count_b`
      5. `max_page_text_levenshtein_ratio`
      6. `bbox_shift_px_p95`
      7. `bbox_shift_px_p99`
      8. `token_iou_drop_p95`
   6. `artifact_paths`
9. `failed_check_ids[]`

Check object required fields:
1. `check_id`
2. `severity` (`critical|high|medium|low`)
3. `status` (`pass|fail|warn`)
4. `message`
5. `expected`
6. `actual`

## 6) Required Validation Checks
Critical checks:
1. `VAL-LAYOUT-001`: profile schema and required keys are valid.
2. `VAL-LAYOUT-002`: renderer binary version matches pinned profile.
3. `VAL-LAYOUT-003`: required fonts are available; fallback policy satisfied.
4. `VAL-LAYOUT-004`: repeat A and repeat B render successfully.
5. `VAL-LAYOUT-005`: page counts are equal (if `require_equal_page_count=true`).
6. `VAL-LAYOUT-006`: token count delta <= `max_token_count_delta_abs`.
7. `VAL-LAYOUT-007`: per-page text drift <= `max_page_text_levenshtein_ratio`.
8. `VAL-LAYOUT-008`: bbox shift p95/p99 within profile thresholds.
9. `VAL-LAYOUT-009`: token IoU drop p95 within profile threshold.
10. `VAL-LAYOUT-010`: all required artifacts exist and hashes are recorded.

High checks:
1. `VAL-LAYOUT-011`: no forbidden renderer flags are present at runtime.
2. `VAL-LAYOUT-012`: CSS override injection was applied.
3. `VAL-LAYOUT-013`: deterministic hash components are stable across repeats.

## 7) Drift Metric Definitions
1. `page_text_levenshtein_ratio`:
   1. Levenshtein distance between page text A/B divided by max page text length.
2. `bbox_shift_px`:
   1. Euclidean center shift for matched tokens in page coordinates.
3. `token_iou_drop`:
   1. `1 - IoU(bbox_a, bbox_b)` for matched tokens.
4. Token matching key:
   1. `(normalized_token_text, page_number, ordinal_on_page)`.

## 8) Artifact Requirements
Per document:
1. `render_repeat_a.pdf`
2. `render_repeat_b.pdf`
3. `bbox_tokens_repeat_a.jsonl`
4. `bbox_tokens_repeat_b.jsonl`
5. `render_run_manifest.json`
6. `layout_render_drift_report.json` (single file mode) or aggregate report (batch)

Manifest must include:
1. Renderer version.
2. Profile hash.
3. Font inventory snapshot.
4. Full command line with effective options.

## 9) Integration Policy
1. Layout-sidecar confidence is non-authoritative.
2. If validator fails for a document, ML layout signal must be ignored for that document.
3. If validator passes, layout signal can be used only for:
   1. review recommendation
   2. abstain recommendation
   3. parent-link veto
4. Silent parse-tree overwrite is forbidden.

## 10) CI/Day-Bundle Integration
1. For any run using layout-sidecar confidence, validator report is required in day artifacts.
2. Day-bundle validator should enforce:
   1. `VAL-LAYOUT-DAY-001`: drift report exists and has `status=pass`.
   2. `VAL-LAYOUT-DAY-002`: profile hash in report matches profile hash in run manifest.
   3. `VAL-LAYOUT-DAY-003`: non-passing layout report forces `layout_signal_consumed=false`.

## 11) Definition of Done
1. `config/layout_render_profile_v1.json` exists and is treated as binding input.
2. `scripts/validate_layout_render_drift.py` implements the CLI contract and exits with the required codes.
3. A sample run artifact set is produced and validated in CI or pre-merge workflow.
