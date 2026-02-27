# Parser V2 Solver Solution Contract v1
Date: 2026-02-27  
Status: Active (M4)

## Objective
Define the solver output format for globally consistent clause trees.

## Solution Record
Required fields:
1. `parse_run_id`
2. `parser_version`
3. `section_key`
4. `selected_node_candidates`: list of chosen node candidate ids
5. `selected_parent_edges`: list of chosen edge ids
6. `abstained_token_ids`: list
7. `objective_score`: float
8. `objective_components`: map of weighted terms
9. `top_k_alternatives`: list with scores for margin computation
10. `solver_diagnostics`: map with runtime, pruning stats, warnings
11. `nodes`: derived node records (see below)
12. `section_parse_status`
13. `section_reason_codes`
14. `critical_node_abstain_ratio`

## Derived Tree Output
Required per node:
1. `clause_id`
2. `parent_id`
3. `depth`
4. `level_type`
5. `span_start`
6. `span_end`
7. `is_structural_candidate`
8. `xref_suspected`
9. `parse_status`
10. `abstain_reason_codes`
11. `solver_margin`
12. `confidence_score`

## Margin and Ambiguity
Required fields:
1. `top1_score`
2. `top2_score`
3. `margin_abs` (`top1_score - top2_score`)
4. `margin_ratio`

Rules:
1. Margin drives confidence and abstain policies.
2. Missing `top2` implies high margin by definition but must be explicit.
3. MVP solver computes `top2` as objective minus average token margin.

## Invariants
1. Selected edges produce an acyclic forest.
2. Every selected node has exactly one selected parent edge or root edge.
3. Node spans are non-inverted and parent-child ordering is consistent.

## Failure Behavior
If solver cannot satisfy hard constraints:
1. Emit `status=abstain_section`.
2. Emit `hard_conflict_reasons`.
3. Emit no partial implicit tree.

## Determinism
1. `parse_run_id` is deterministic from `section_key + selected_node_candidates + abstained_token_ids`.
2. Selection tie-break order:
3. highest score
4. shallowest depth
5. lexical candidate id

## Implementation Reference
1. Solver implementation: `src/agent/parser_v2/solver.py`
2. Output types: `src/agent/parser_v2/solution_types.py`
3. Snapshot fixture: `tests/fixtures/parser_v2/solver_snapshot_v1.json`
