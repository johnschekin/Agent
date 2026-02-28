# Parser V2 M6-T3 SLO Readiness Report
Date: 2026-02-27  
Owner: Parsing Program  
Status: Completed (`M6-T3`)

## Scope
Finalize shadow-hardening readiness for `parser_v2` using:
1. M6-T2 large-slice dual-run outputs.
2. Threshold calibration sweep across the same slices.
3. Manual audit sample log from high-signal sections.

## Input Artifacts
1. `artifacts/parser_v2_dual_run_m6_t2_summary.json`
2. `artifacts/parser_v2_m6_t3_threshold_sweep.json`
3. `artifacts/parser_v2_m6_t3_default_profile_diagnostics.json`
4. `artifacts/parser_v2_m6_t3_readiness_summary.json`

## Baseline (Current Defaults)
Solver defaults:
1. `abstain_margin_threshold=0.08`
2. `review_margin_threshold=0.20`
3. `section_abstain_ratio_threshold=0.40`

Across 2,600 sections:
1. `accepted`: 7 (`0.27%`)
2. `review`: 112 (`4.31%`)
3. `abstain`: 2,481 (`95.42%`)

Top section reason codes:
1. `low_margin`: 2,590
2. `xref_conflict`: 2,538
3. `insufficient_context`: 2,481

Top node reason codes:
1. `low_margin`: 223,401
2. `xref_conflict`: 55,736

## Threshold Sweep (Same 2,600 Sections)
Profiles tested:
1. `default`: `0.08 / 0.20 / 0.40`
2. `calib_m1`: `0.06 / 0.16 / 0.55`
3. `calib_m2`: `0.05 / 0.14 / 0.65`
4. `calib_aggr`: `0.04 / 0.12 / 0.75`
5. `calib_aggr2`: `0.03 / 0.10 / 0.82`

Results:
1. `default`: abstain `95.42%`, review `4.31%`, accepted `0.27%`
2. `calib_m1`: abstain `12.27%`, review `87.46%`, accepted `0.27%`
3. `calib_m2`: abstain `2.58%`, review `97.15%`, accepted `0.27%`
4. `calib_aggr`: abstain `0.77%`, review `98.96%`, accepted `0.27%`
5. `calib_aggr2`: abstain `0.12%`, review `99.62%`, accepted `0.27%`

Max-permissive ceiling check (`0.00 / 0.00 / 1.00`):
1. `accepted`: 7 (`0.27%`)
2. `review`: 2,592 (`99.69%`)
3. `abstain`: 1 (`0.04%`)

Interpretation:
1. Threshold-only tuning mostly converts `abstain -> review`.
2. It does not materially increase `accepted`.
3. Current acceptance bottleneck is scoring/policy logic, not calibration alone.

## Manual Audit Log (Sample)
Sampled rows from default-profile diagnostics:

1. `GFV1-XREF_VS_STRUCTURAL-0151` (`2.1`)  
Status: `accepted`, overlap `1.00`, reasons: none.  
Audit: Correct behavior; v2 aligns with v1 and no abstain/review trigger.

2. `GFV1-LINKING_CONTRACT-0474` (`3.25`)  
Status: `accepted`, overlap `1.00`, reasons: none.  
Audit: Correct behavior; clean section where solver is decisive.

3. `GFV1-XREF_VS_STRUCTURAL-0145` (`8.02`)  
Status: `review`, overlap `1.00`, reasons: `xref_conflict`.  
Audit: Conservative but defensible; structure is good, citation context triggers review.

4. `GFV1-DEFINED_TERM_BOUNDARY-0341` (`10.09`)  
Status: `review`, overlap `1.00`, reasons: `low_margin`.  
Audit: Conservative classification despite full overlap; suggests margin thresholds are not the core issue.

5. `GFV1-LINKING_CONTRACT-0478` (`7.13`)  
Status: `review`, overlap `1.00`, reasons: `low_margin`.  
Audit: Same pattern as above; high-quality parse still routed to review.

6. `GFV1-XREF_VS_STRUCTURAL-0176` (`6.06`)  
Status: `abstain`, overlap `0.60`, reasons: `insufficient_context`, `low_margin`, `xref_conflict`.  
Audit: Mixed-quality parse; abstain is plausible under strict policy.

7. `GFV1-XREF_VS_STRUCTURAL-0147` (`2.09`)  
Status: `abstain`, overlap `0.50`, reasons: `insufficient_context`, `low_margin`, `xref_conflict`.  
Audit: Conservative abstain is reasonable given parent/citation ambiguity.

8. `GFV1C-TRUE_ROOT_HIGH_LETTER-0954` (`6.02`)  
Status: `abstain`, overlap `0.507463`, reasons: `insufficient_context`, `low_margin`, `xref_conflict`.  
Audit: High-letter continuation family still unresolved enough to justify abstain/review routing.

Manual-audit takeaway:
1. Statusing is internally consistent.
2. Decision boundary is too conservative for production auto-accept volume.

## Readiness Verdict
`NOT READY` for M7 cutover.

Why:
1. Accepted rate is `0.27%` under default and unchanged even under max-permissive thresholds.
2. Nearly all recoverable volume becomes `review`, not `accepted`.
3. Main blockers are solver scoring and policy logic (`low_margin` + `xref_conflict` concentration), not threshold calibration.

## Recommended Next Step
Short-term shadow profile for continued diagnostics:
1. Use `calib_m1` (`0.06 / 0.16 / 0.55`) to reduce abstain backlog while preserving conservative posture.

Required before cutover:
1. Update scoring/feature logic (especially xref and margin behavior).
2. Add category-aware acceptance policy for low-risk fixture families.
3. Re-run M6 shadow and re-check SLO gates after logic changes.
