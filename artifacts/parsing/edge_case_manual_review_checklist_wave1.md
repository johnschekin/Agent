# Edge-Case Manual Review Checklist (Wave 1)

- Source DB: `corpus_index/corpus.duckdb`
- Sampling rule: first `5` flagged structural clauses per `(doc_id, section_number)`
- Categories represented: `structural_child_of_nonstruct_parent`, `inline_high_letter_branch`
- Checklist CSV: `artifacts/parsing/edge_case_manual_review_checklist_wave1.csv`

## Scope Summary
- `depth2_wave1`: 20 docs, 402 sections, 1497 review rows
- `root_wave1`: 10 docs, 249 sections, 912 review rows

## Reviewer Fields
- `review_status`: `valid_parser_issue` | `false_positive` | `unclear`
- `review_issue_type`: short label (e.g., `missing_parent_chain`, `over_demoted_parent`, `expected_root_xyz`)
- `review_action`: proposed fix action (e.g., `adjust_disambiguation`, `adjust_singleton_penalty`, `no_change`)
- `review_notes`: free-form rationale

## Suggested Pass Order
1. Review `depth2_wave1` rows first (dominant regression bucket).
2. Then review `root_wave1` rows to isolate true root `(x)/(y)/(z)` patterns.
