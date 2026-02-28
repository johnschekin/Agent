# Hybrid Parser/ML Gate Review Template v1
Date: 2026-02-27
Status: Active
Owner: Program Owner

## Meeting Header
1. Gate ID: `GL0|GL1|GL2|GL3|GL4|GL5`
2. Run ID:
3. Review timestamp (UTC):
4. Reviewer(s):

## Required Inputs
1. `day_validator_report.json` path + SHA256
2. `day_run_manifest.json` path + SHA256
3. `day_blocker_register.json` path + SHA256
4. `day_gate_summary.json` path + SHA256
5. Red-team audit memo path + SHA256

## Gate Metrics Table
1. Metric name
2. Threshold
3. Observed value
4. Pass/Fail
5. Evidence artifact path

## Canonical Routing and Provenance
1. Workspace dirty at run time: `true|false`
2. Canonical policy artifact path:
3. Canonical primary output pointers verified: `yes|no`
4. Commit provenance alignment verified: `yes|no`

## Blocker Review
1. Open blockers (`day_close` scope)
2. Open blockers (`launch` scope)
3. Newly created blockers this gate
4. Closed blockers this gate (with resolution evidence)

## Decision
1. Decision state: `GO|NO-GO|CONDITIONAL GO (shadow only)`
2. Decision rationale:
3. Required follow-up actions with owner + ETA:

## Sign-Off
1. Parser technical owner:
2. Data/adjudication owner:
3. Operations owner:
4. Product owner:
