"""Parser_v2 lexer built on enumerator scanning primitives."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from agent.enumerator import (
    CANONICAL_DEPTH,
    EnumeratorMatch,
    compute_indentation,
    compute_line_starts,
    scan_enumerators,
)
from agent.parser_v2.normalization import normalize_for_parser_v2
from agent.parser_v2.types import CandidateType, LexerToken, NormalizedText, SourceSpan


_CANDIDATE_ORDER: dict[CandidateType, int] = {
    "alpha": CANONICAL_DEPTH["alpha"],
    "roman": CANONICAL_DEPTH["roman"],
    "caps": CANONICAL_DEPTH["caps"],
    "numeric": CANONICAL_DEPTH["numeric"],
}

_XREF_LEXICON_RE = re.compile(
    r"\b(?:section|sections|article|articles|clause|clauses|paragraph|paragraphs)\b",
    re.IGNORECASE,
)
_XREF_PREPOSITION_RE = re.compile(
    r"\b(?:pursuant to|subject to|in accordance with|defined in|under)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class _TokenAccumulator:
    """Grouped interpretations for one lexer token boundary."""

    key: tuple[int, int, str]
    first_match: EnumeratorMatch
    candidate_types: set[CandidateType]
    ordinal_by_type: dict[CandidateType, int]


def _normalize_label(raw_label: str) -> str:
    label = raw_label.strip()
    if label.endswith("."):
        label = label[:-1]
    if label.startswith("(") and label.endswith(")"):
        label = label[1:-1]
    return label.strip()


def _is_line_start(position: int, line_starts: list[int], text: str) -> bool:
    idx = bisect.bisect_right(line_starts, position) - 1
    if idx < 0:
        return position == 0
    line_start = line_starts[idx]
    return text[line_start:position].strip() == ""


def _xref_features(text: str, start: int, end: int) -> dict[str, bool]:
    lookback = text[max(0, start - 120):start]
    lookahead = text[end:min(len(text), end + 120)]
    return {
        "xref_keyword_pre": bool(_XREF_LEXICON_RE.search(lookback)),
        "xref_keyword_post": bool(_XREF_LEXICON_RE.search(lookahead)),
        "xref_preposition_pre": bool(_XREF_PREPOSITION_RE.search(lookback)),
    }


def lex_enumerator_tokens(
    payload: str | NormalizedText,
) -> tuple[NormalizedText, list[LexerToken]]:
    """Emit parser_v2 token stream from normalized text.

    Returns:
    1. `NormalizedText` payload (input is normalized if needed)
    2. sorted list of `LexerToken`
    """

    normalized = payload if isinstance(payload, NormalizedText) else normalize_for_parser_v2(payload)
    text = normalized.normalized_text
    line_starts = compute_line_starts(text)
    matches = scan_enumerators(text, line_starts, deduplicate_alpha_roman=False)

    grouped: dict[tuple[int, int, str], _TokenAccumulator] = {}
    for match in matches:
        level_type = match.level_type
        if level_type not in _CANDIDATE_ORDER:
            continue
        key = (match.position, match.match_end, match.raw_label)
        acc = grouped.get(key)
        if acc is None:
            acc = _TokenAccumulator(
                key=key,
                first_match=match,
                candidate_types=set(),
                ordinal_by_type={},
            )
            grouped[key] = acc
        acc.candidate_types.add(level_type)
        acc.ordinal_by_type[level_type] = int(match.ordinal)

    rows = sorted(grouped.values(), key=lambda row: (row.key[0], row.key[1], row.key[2]))
    tokens: list[LexerToken] = []
    for idx, row in enumerate(rows, start=1):
        start = row.key[0]
        end = row.key[1]
        match = row.first_match
        line_idx = bisect.bisect_right(line_starts, start) - 1
        line_start = line_starts[line_idx] if line_idx >= 0 else 0
        column_idx = start - line_start
        line_end = text.find("\n", line_start)
        if line_end < 0:
            line_end = len(text)
        candidate_types = tuple(
            sorted(row.candidate_types, key=lambda item: _CANDIDATE_ORDER[item]),
        )
        indent = compute_indentation(start, text, line_starts)
        is_line_start = _is_line_start(start, line_starts, text)
        token = LexerToken(
            token_id=f"tok_{idx:05d}_{start}",
            raw_label=match.raw_label,
            normalized_label=_normalize_label(match.raw_label),
            position_start=start,
            position_end=end,
            line_index=max(0, line_idx),
            column_index=max(0, column_idx),
            is_line_start=is_line_start,
            indentation_score=round(indent, 4),
            candidate_types=candidate_types,
            ordinal_by_type=row.ordinal_by_type,
            xref_context_features=_xref_features(text, start, end),
            layout_features={
                "anchored_boundary": bool(match.is_anchored),
                "line_char_count": int(line_end - line_start),
                "line_start_match": is_line_start,
            },
            source_span=SourceSpan(char_start=start, char_end=end),
        )
        tokens.append(token)

    return normalized, tokens
