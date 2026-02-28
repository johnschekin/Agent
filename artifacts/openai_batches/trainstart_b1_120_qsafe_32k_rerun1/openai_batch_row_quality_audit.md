# OpenAI Batch Row Quality Audit

{
  "row_count": 57,
  "quality_tier_counts": {
    "pass": 49,
    "fail_unusable": 8
  },
  "decision_counts_parseable_only": {
    "review": 9,
    "abstain": 31,
    "accepted": 9
  },
  "finish_reason_counts": {
    "stop": 49,
    "length": 8
  },
  "top_failed_checks": {
    "json_parseable": 8,
    "finish_reason_not_length": 8,
    "required_top_level": 8,
    "schema_version_ok": 8,
    "source_type_ok": 8,
    "decision_ok": 8,
    "split_ok": 8,
    "reason_codes_len_1_3": 8,
    "adjudication_fields": 8,
    "ambiguity_class_ok": 8,
    "human_verified_false": 8,
    "adjudicator_id_ok": 8,
    "adjudicated_at_ok": 8,
    "fixture_id_preserved": 8,
    "category_preserved": 8,
    "doc_id_preserved": 8,
    "section_number_preserved": 8,
    "snapshot_id_preserved": 8,
    "split_preserved": 8,
    "text_raw_blank": 8
  }
}

## Rows
| queue_item_id | quality_tier | decision | category | nodes | finish_reason | failed_checks |
|---|---|---|---|---:|---|---|
| P1-ADJUDICATION-TRAINSTART-0031 | pass | review | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0032 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0033 | pass | review | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0034 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0035 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0036 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0037 | pass | review | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0038 | fail_unusable |  | high_letter_continuation |  | length | json_parseable, finish_reason_not_length, required_top_level, schema_version_ok, source_type_ok, decision_ok, split_ok, reason_codes_len_1_3, adjudication_fields, ambiguity_class_ok, human_verified_false, adjudicator_id_ok, adjudicated_at_ok, fixture_id_preserved, category_preserved, doc_id_preserved, section_number_preserved, snapshot_id_preserved, split_preserved, text_raw_blank, text_char_start_zero, text_char_end_match, nodes_structurally_valid |
| P1-ADJUDICATION-TRAINSTART-0039 | fail_unusable |  | high_letter_continuation |  | length | json_parseable, finish_reason_not_length, required_top_level, schema_version_ok, source_type_ok, decision_ok, split_ok, reason_codes_len_1_3, adjudication_fields, ambiguity_class_ok, human_verified_false, adjudicator_id_ok, adjudicated_at_ok, fixture_id_preserved, category_preserved, doc_id_preserved, section_number_preserved, snapshot_id_preserved, split_preserved, text_raw_blank, text_char_start_zero, text_char_end_match, nodes_structurally_valid |
| P1-ADJUDICATION-TRAINSTART-0040 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0041 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0042 | pass | review | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0043 | pass | accepted | high_letter_continuation | 1 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0044 | pass | review | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0045 | fail_unusable |  | high_letter_continuation |  | length | json_parseable, finish_reason_not_length, required_top_level, schema_version_ok, source_type_ok, decision_ok, split_ok, reason_codes_len_1_3, adjudication_fields, ambiguity_class_ok, human_verified_false, adjudicator_id_ok, adjudicated_at_ok, fixture_id_preserved, category_preserved, doc_id_preserved, section_number_preserved, snapshot_id_preserved, split_preserved, text_raw_blank, text_char_start_zero, text_char_end_match, nodes_structurally_valid |
| P1-ADJUDICATION-TRAINSTART-0046 | fail_unusable |  | high_letter_continuation |  | length | json_parseable, finish_reason_not_length, required_top_level, schema_version_ok, source_type_ok, decision_ok, split_ok, reason_codes_len_1_3, adjudication_fields, ambiguity_class_ok, human_verified_false, adjudicator_id_ok, adjudicated_at_ok, fixture_id_preserved, category_preserved, doc_id_preserved, section_number_preserved, snapshot_id_preserved, split_preserved, text_raw_blank, text_char_start_zero, text_char_end_match, nodes_structurally_valid |
| P1-ADJUDICATION-TRAINSTART-0047 | pass | review | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0048 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0049 | pass | review | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0050 | fail_unusable |  | high_letter_continuation |  | length | json_parseable, finish_reason_not_length, required_top_level, schema_version_ok, source_type_ok, decision_ok, split_ok, reason_codes_len_1_3, adjudication_fields, ambiguity_class_ok, human_verified_false, adjudicator_id_ok, adjudicated_at_ok, fixture_id_preserved, category_preserved, doc_id_preserved, section_number_preserved, snapshot_id_preserved, split_preserved, text_raw_blank, text_char_start_zero, text_char_end_match, nodes_structurally_valid |
| P1-ADJUDICATION-TRAINSTART-0051 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0052 | pass | accepted | high_letter_continuation | 1 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0053 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0055 | pass | review | high_letter_continuation | 1 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0057 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0058 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0060 | pass | abstain | high_letter_continuation | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0091 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0092 | fail_unusable |  | xref_vs_structural |  | length | json_parseable, finish_reason_not_length, required_top_level, schema_version_ok, source_type_ok, decision_ok, split_ok, reason_codes_len_1_3, adjudication_fields, ambiguity_class_ok, human_verified_false, adjudicator_id_ok, adjudicated_at_ok, fixture_id_preserved, category_preserved, doc_id_preserved, section_number_preserved, snapshot_id_preserved, split_preserved, text_raw_blank, text_char_start_zero, text_char_end_match, nodes_structurally_valid |
| P1-ADJUDICATION-TRAINSTART-0093 | pass | accepted | xref_vs_structural | 1 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0094 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0095 | pass | accepted | xref_vs_structural | 1 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0096 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0097 | pass | review | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0098 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0099 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0100 | fail_unusable |  | xref_vs_structural |  | length | json_parseable, finish_reason_not_length, required_top_level, schema_version_ok, source_type_ok, decision_ok, split_ok, reason_codes_len_1_3, adjudication_fields, ambiguity_class_ok, human_verified_false, adjudicator_id_ok, adjudicated_at_ok, fixture_id_preserved, category_preserved, doc_id_preserved, section_number_preserved, snapshot_id_preserved, split_preserved, text_raw_blank, text_char_start_zero, text_char_end_match, nodes_structurally_valid |
| P1-ADJUDICATION-TRAINSTART-0101 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0102 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0103 | pass | accepted | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0104 | pass | accepted | xref_vs_structural | 1 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0105 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0106 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0107 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0108 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0109 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0110 | fail_unusable |  | xref_vs_structural |  | length | json_parseable, finish_reason_not_length, required_top_level, schema_version_ok, source_type_ok, decision_ok, split_ok, reason_codes_len_1_3, adjudication_fields, ambiguity_class_ok, human_verified_false, adjudicator_id_ok, adjudicated_at_ok, fixture_id_preserved, category_preserved, doc_id_preserved, section_number_preserved, snapshot_id_preserved, split_preserved, text_raw_blank, text_char_start_zero, text_char_end_match, nodes_structurally_valid |
| P1-ADJUDICATION-TRAINSTART-0111 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0112 | pass | accepted | xref_vs_structural | 1 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0113 | pass | accepted | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0114 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0115 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0116 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0117 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0118 | pass | abstain | xref_vs_structural | 0 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0119 | pass | accepted | xref_vs_structural | 1 | stop |  |
| P1-ADJUDICATION-TRAINSTART-0120 | pass | abstain | xref_vs_structural | 0 | stop |  |
