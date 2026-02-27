"""Parser v2 foundations: normalization and lexer contracts."""

from agent.parser_v2.lexer import lex_enumerator_tokens
from agent.parser_v2.normalization import normalize_for_parser_v2
from agent.parser_v2.types import (
    CandidateType,
    LexerToken,
    NormalizedText,
    SourceSpan,
)

__all__ = [
    "CandidateType",
    "LexerToken",
    "NormalizedText",
    "SourceSpan",
    "lex_enumerator_tokens",
    "normalize_for_parser_v2",
]
