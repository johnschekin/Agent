# Parser V2 Adapter Contract v1
Date: 2026-02-27  
Status: Active (M5)

## Objective
Define how parser_v2 solution output is adapted into legacy clause/link payloads without breaking existing consumers.

## Adapter Output
Top-level payload:
1. `parse_run_id`
2. `parser_version`
3. `section_key`
4. `section_parse_status`
5. `section_reason_codes`
6. `critical_node_abstain_ratio`
7. `abstained_token_ids`
8. `nodes` (legacy-compatible clause node dicts)

Node fields:
1. Legacy keys:
2. `id`, `label`, `depth`, `level_type`, `span_start`, `span_end`
3. `header_text`, `parent_id`, `children_ids`
4. `anchor_ok`, `run_length_ok`, `gap_ok`, `indentation_score`
5. `xref_suspected`, `is_structural_candidate`, `parse_confidence`, `demotion_reason`
6. Parser_v2 additive keys:
7. `parse_status`, `abstain_reason_codes`, `solver_margin`

## Compatibility Rules
1. Existing consumers that rely on legacy keys continue to function.
2. New parser_v2 fields are additive and must not rename legacy keys.
3. Spans can be offset with `global_offset` to align with section-global coordinates.

## Sidecar Persistence Contract
Dual-run sidecar record includes:
1. fixture/source identity
2. parser_v1 node summary + nodes
3. parser_v2 solution + adapted payload
4. v1/v2 comparison summary
5. stable `raw_text_sha256`

Implementation:
1. Adapter: `src/agent/parser_v2/adapter.py`
2. Dual-run + sidecar: `src/agent/parser_v2/dual_run.py`
3. CLI: `scripts/parser_v2_dual_run.py`
