# Parser V2 Candidate Graph Contract v1
Date: 2026-02-27  
Status: Draft (M0 publish)

## Objective
Define the graph representation that captures all plausible clause structures before solving.

## Entities
### 1) Node Candidate (`ClauseNodeCandidate`)
Required fields:
1. `node_candidate_id`
2. `token_id`
3. `type`: `alpha|roman|caps|numeric`
4. `ordinal`
5. `depth_hint`
6. `span_start`
7. `span_end`
8. `feature_vector`: keyed soft signals used by solver objective.

### 2) Parent Edge Candidate (`ParentEdgeCandidate`)
Required fields:
1. `edge_id`
2. `child_candidate_id`
3. `parent_candidate_id` (or `root=true`)
4. `hard_valid`: boolean
5. `hard_invalid_reasons`: list
6. `soft_score_components`: map
7. `edge_penalties`: map (xref, depth, crossing, discontinuity)

## Hard Constraints Encoding
1. `acyclic_parenting`
2. `parent_exists`
3. `single_parent_or_root`
4. `single_type_per_token_or_abstain`
5. `span_ordering_valid`
6. `depth_transition_valid`

## Diagnostics Payload
Each graph build must optionally emit:
1. `graph_stats` (`node_candidate_count`, `edge_candidate_count`)
2. `pruned_edges_by_reason`
3. `ambiguous_tokens`
4. `construction_warnings`

## Invariants
1. Every `child_candidate_id` has at least one parent-or-root edge unless token is explicitly abstain-eligible.
2. No edge references missing candidate nodes.
3. Graph builder cannot mutate lexer tokens.

## Determinism Rules
1. Candidate ID generation must be stable and deterministic.
2. Edge generation and pruning order must be deterministic.
