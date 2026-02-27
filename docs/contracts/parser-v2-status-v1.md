# Parser V2 Parse Status Contract v1
Date: 2026-02-27  
Status: Draft (M0 publish)

## Objective
Define parser status and abstain reason semantics for linking workflows, review UI, and evidence exports.

## Status Fields
Node-level required:
1. `parse_status`: `accepted|review|abstain`
2. `abstain_reason_codes`: array (empty when accepted/review without abstention)
3. `solver_margin`
4. `confidence_score`

Section-level required:
1. `section_parse_status`: `accepted|review|abstain`
2. `section_reason_codes`
3. `critical_node_abstain_ratio`

## Reason Code Minimum Set
1. `low_margin`
2. `xref_conflict`
3. `parent_conflict`
4. `depth_conflict`
5. `span_conflict`
6. `layout_uncertain`
7. `normalization_noise`
8. `insufficient_context`

## Operational Rules
1. `accepted`: eligible for auto-linking (subject to downstream policy gates).
2. `review`: visible in review queues; not auto-linked by default.
3. `abstain`: excluded from auto-linking; must include reason codes.

## Evidence / Linking Integration
1. Parser reason codes must be merged into link `policy_reasons`.
2. `parse_status` must be persisted with candidate/link evidence rows.
3. UI must display status badges and reason chips.

## Backward Compatibility
1. Existing consumers using structural fields only must continue to function.
2. New status fields are additive and optional during dual-run period.
3. On cutover, status fields become required for parser_v2 paths.

## Governance
1. Any new reason code requires contract update.
2. Status threshold changes require calibration note + version entry.
