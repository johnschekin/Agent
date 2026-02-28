# Batch Row Deep Dive Quality (57 rows)

{
  "rows_total": 57,
  "quality_grade_counts": {
    "Q2_PASS_BUT_LOW_UTILITY": 49,
    "Q0_FAIL_UNUSABLE": 8
  },
  "decision_counts": {
    "review": 9,
    "abstain": 31,
    "accepted": 9
  },
  "node_count_distribution_parseable": {
    "0": 41,
    "1": 8
  },
  "policy_risk_rows": 1,
  "training_utility_counts": {
    "low_for_parser_training_use_for_queue": 9,
    "low_for_parser_training_use_for_abstain_model": 31,
    "none": 8,
    "medium_section_level_only": 7,
    "low_negative_only": 2
  }
}

| queue_item_id | grade | decision | category | nodes | utility | policy_risk | next_action |
|---|---|---|---|---:|---|---|---|
| P1-ADJUDICATION-TRAINSTART-0031 | Q2_PASS_BUT_LOW_UTILITY | review | high_letter_continuation | 0 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0032 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0033 | Q2_PASS_BUT_LOW_UTILITY | review | high_letter_continuation | 0 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0034 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0035 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0036 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0037 | Q2_PASS_BUT_LOW_UTILITY | review | high_letter_continuation | 0 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0038 | Q0_FAIL_UNUSABLE |  | high_letter_continuation |  | none | false | rerun_row_with_output_budget_controls |
| P1-ADJUDICATION-TRAINSTART-0039 | Q0_FAIL_UNUSABLE |  | high_letter_continuation |  | none | false | rerun_row_with_output_budget_controls |
| P1-ADJUDICATION-TRAINSTART-0040 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0041 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0042 | Q2_PASS_BUT_LOW_UTILITY | review | high_letter_continuation | 0 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0043 | Q2_PASS_BUT_LOW_UTILITY | accepted | high_letter_continuation | 1 | medium_section_level_only | false | manual_refine_clause_level_spans_if_for_token_training |
| P1-ADJUDICATION-TRAINSTART-0044 | Q2_PASS_BUT_LOW_UTILITY | review | high_letter_continuation | 0 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0045 | Q0_FAIL_UNUSABLE |  | high_letter_continuation |  | none | false | rerun_row_with_output_budget_controls |
| P1-ADJUDICATION-TRAINSTART-0046 | Q0_FAIL_UNUSABLE |  | high_letter_continuation |  | none | false | rerun_row_with_output_budget_controls |
| P1-ADJUDICATION-TRAINSTART-0047 | Q2_PASS_BUT_LOW_UTILITY | review | high_letter_continuation | 0 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0048 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0049 | Q2_PASS_BUT_LOW_UTILITY | review | high_letter_continuation | 0 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0050 | Q0_FAIL_UNUSABLE |  | high_letter_continuation |  | none | false | rerun_row_with_output_budget_controls |
| P1-ADJUDICATION-TRAINSTART-0051 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0052 | Q2_PASS_BUT_LOW_UTILITY | accepted | high_letter_continuation | 1 | medium_section_level_only | false | manual_refine_clause_level_spans_if_for_token_training |
| P1-ADJUDICATION-TRAINSTART-0053 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0055 | Q2_PASS_BUT_LOW_UTILITY | review | high_letter_continuation | 1 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0057 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0058 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0060 | Q2_PASS_BUT_LOW_UTILITY | abstain | high_letter_continuation | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0091 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0092 | Q0_FAIL_UNUSABLE |  | xref_vs_structural |  | none | false | rerun_row_with_output_budget_controls |
| P1-ADJUDICATION-TRAINSTART-0093 | Q2_PASS_BUT_LOW_UTILITY | accepted | xref_vs_structural | 1 | medium_section_level_only | false | manual_refine_clause_level_spans_if_for_token_training |
| P1-ADJUDICATION-TRAINSTART-0094 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0095 | Q2_PASS_BUT_LOW_UTILITY | accepted | xref_vs_structural | 1 | medium_section_level_only | false | manual_refine_clause_level_spans_if_for_token_training |
| P1-ADJUDICATION-TRAINSTART-0096 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0097 | Q2_PASS_BUT_LOW_UTILITY | review | xref_vs_structural | 0 | low_for_parser_training_use_for_queue | false | send_to_manual_adjudication_for_authoritative_label |
| P1-ADJUDICATION-TRAINSTART-0098 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0099 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0100 | Q0_FAIL_UNUSABLE |  | xref_vs_structural |  | none | false | rerun_row_with_output_budget_controls |
| P1-ADJUDICATION-TRAINSTART-0101 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0102 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | true | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0103 | Q2_PASS_BUT_LOW_UTILITY | accepted | xref_vs_structural | 0 | low_negative_only | false | manual_verify_inline_only_then_keep_or_relabel |
| P1-ADJUDICATION-TRAINSTART-0104 | Q2_PASS_BUT_LOW_UTILITY | accepted | xref_vs_structural | 1 | medium_section_level_only | false | manual_refine_clause_level_spans_if_for_token_training |
| P1-ADJUDICATION-TRAINSTART-0105 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0106 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0107 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0108 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0109 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0110 | Q0_FAIL_UNUSABLE |  | xref_vs_structural |  | none | false | rerun_row_with_output_budget_controls |
| P1-ADJUDICATION-TRAINSTART-0111 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0112 | Q2_PASS_BUT_LOW_UTILITY | accepted | xref_vs_structural | 1 | medium_section_level_only | false | manual_refine_clause_level_spans_if_for_token_training |
| P1-ADJUDICATION-TRAINSTART-0113 | Q2_PASS_BUT_LOW_UTILITY | accepted | xref_vs_structural | 0 | low_negative_only | false | manual_verify_inline_only_then_keep_or_relabel |
| P1-ADJUDICATION-TRAINSTART-0114 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0115 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0116 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0117 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0118 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
| P1-ADJUDICATION-TRAINSTART-0119 | Q2_PASS_BUT_LOW_UTILITY | accepted | xref_vs_structural | 1 | medium_section_level_only | false | manual_refine_clause_level_spans_if_for_token_training |
| P1-ADJUDICATION-TRAINSTART-0120 | Q2_PASS_BUT_LOW_UTILITY | abstain | xref_vs_structural | 0 | low_for_parser_training_use_for_abstain_model | false | retain_for_abstain_calibration_not_token_training |
