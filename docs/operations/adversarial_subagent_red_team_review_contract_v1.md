# Adversarial Subagent Red-Team Review Contract v1
Date: 2026-02-27
Status: Binding when `day_gate_summary.red_team_status` is `in_review|complete`

## Required Artifact
1. JSON file under day bundle, recommended path:
   1. `red_team/adversarial_subagent_review_<day_id>.json`

## Required Fields
1. `schema_version`
2. `day_id`
3. `review_mode` (must be `adversarial_subagent`)
4. `subagent_id`
5. `adversarial_findings` (non-empty list)
6. `verdict` (`pass|partial_pass|fail`)
7. `completed_at` (ISO-8601)

## Manifest Pointer
1. `day_run_manifest.output_artifacts.red_team_adversarial_review` must point to the artifact path.

## Minimal Example
```json
{
  "schema_version": "red-team-adversarial-subagent-review-v1",
  "day_id": "day3",
  "review_mode": "adversarial_subagent",
  "subagent_id": "agent-redteam-007",
  "adversarial_findings": [
    {
      "severity": "high",
      "summary": "example finding",
      "evidence": "artifacts/launch_run_2026-02-28_day3/..."
    }
  ],
  "verdict": "partial_pass",
  "completed_at": "2026-02-28T23:55:00+00:00"
}
```
