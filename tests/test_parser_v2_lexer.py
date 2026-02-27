"""Tests for parser_v2 normalization and lexer scaffolding."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.parser_v2.lexer import lex_enumerator_tokens
from agent.parser_v2.normalization import normalize_for_parser_v2


def _token_to_snapshot(token: object) -> dict[str, object]:
    from agent.parser_v2.types import LexerToken

    row = token
    assert isinstance(row, LexerToken)
    return {
        "token_id": row.token_id,
        "raw_label": row.raw_label,
        "normalized_label": row.normalized_label,
        "position_start": row.position_start,
        "position_end": row.position_end,
        "line_index": row.line_index,
        "column_index": row.column_index,
        "is_line_start": row.is_line_start,
        "indentation_score": row.indentation_score,
        "candidate_types": list(row.candidate_types),
        "ordinal_by_type": dict(sorted(row.ordinal_by_type.items())),
        "xref_context_features": dict(sorted(row.xref_context_features.items())),
        "layout_features": dict(sorted(row.layout_features.items())),
        "source_span": {
            "char_start": row.source_span.char_start,
            "char_end": row.source_span.char_end,
        },
    }


class TestParserV2Normalization:
    def test_normalize_text_flags_and_offsets(self) -> None:
        raw = "(a)\r\nTerm\u00a0Loan\r(b)\u200bNext"
        normalized = normalize_for_parser_v2(raw)
        assert normalized.normalized_text == "(a)\nTerm Loan\n(b)Next"
        assert normalized.normalization_flags["crlf_normalized"] is True
        assert normalized.normalization_flags["nbsp_normalized"] is True
        assert normalized.normalization_flags["zero_width_removed"] is True
        assert len(normalized.raw_to_normalized) == len(raw) + 1
        assert len(normalized.normalized_to_raw) == len(normalized.normalized_text) + 1
        assert normalized.normalized_to_raw[-1] == len(raw)

    def test_normalization_is_deterministic(self) -> None:
        raw = "(a)\r\nAlpha\r\n(b)\r\nBeta"
        first = normalize_for_parser_v2(raw)
        second = normalize_for_parser_v2(raw)
        assert first.normalized_text == second.normalized_text
        assert first.raw_to_normalized == second.raw_to_normalized
        assert first.normalized_to_raw == second.normalized_to_raw


class TestParserV2Lexer:
    def test_lexer_emits_sorted_contract_tokens(self) -> None:
        text = "(a) Parent clause.\n(i) Child one.\n(ii) Child two.\n"
        normalized, tokens = lex_enumerator_tokens(text)
        assert normalized.normalized_text == text
        assert len(tokens) >= 3
        positions = [token.position_start for token in tokens]
        assert positions == sorted(positions)
        for token in tokens:
            assert token.position_start < token.position_end
            assert token.candidate_types
            for candidate in token.candidate_types:
                assert candidate in token.ordinal_by_type

    def test_lexer_keeps_ambiguous_alpha_roman_candidates(self) -> None:
        text = "(a) Parent.\n(i) Maybe alpha or roman.\n(ii) Roman signal.\n"
        _, tokens = lex_enumerator_tokens(text)
        token_i = next(token for token in tokens if token.normalized_label == "i")
        assert set(token_i.candidate_types) == {"alpha", "roman"}
        assert token_i.ordinal_by_type["alpha"] == 9
        assert token_i.ordinal_by_type["roman"] == 1

    def test_lexer_emits_xref_context_features(self) -> None:
        text = "subject to clause (i) above, the Borrower may.\n"
        _, tokens = lex_enumerator_tokens(text)
        assert len(tokens) == 1
        token = tokens[0]
        assert token.xref_context_features["xref_preposition_pre"] is True
        assert token.xref_context_features["xref_keyword_pre"] is True

    def test_lexer_snapshot_contract_v1(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "parser_v2" / "token_snapshot_v1.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        text = payload["input_text"]
        _, tokens = lex_enumerator_tokens(text)
        actual = [_token_to_snapshot(token) for token in tokens]
        assert actual == payload["expected_tokens"]
