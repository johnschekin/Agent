"""Core types for parser_v2 normalization and lexing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


type CandidateType = Literal["alpha", "roman", "caps", "numeric"]
type LayoutFeatureValue = bool | int | float | str


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Absolute source span in normalized text."""

    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if self.char_start < 0:
            raise ValueError(f"char_start must be >= 0, got {self.char_start}")
        if self.char_end <= self.char_start:
            raise ValueError(
                f"char_end must be > char_start, got {self.char_end} <= {self.char_start}",
            )


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """Normalized text plus reversible offset maps."""

    raw_text: str
    normalized_text: str
    raw_to_normalized: tuple[int, ...]
    normalized_to_raw: tuple[int, ...]
    normalization_flags: dict[str, bool]
    normalization_version: str = "parser_v2_norm_v1"

    def __post_init__(self) -> None:
        if len(self.raw_to_normalized) != len(self.raw_text) + 1:
            raise ValueError(
                "raw_to_normalized length must equal len(raw_text) + 1",
            )
        if len(self.normalized_to_raw) != len(self.normalized_text) + 1:
            raise ValueError(
                "normalized_to_raw length must equal len(normalized_text) + 1",
            )


@dataclass(frozen=True, slots=True)
class LexerToken:
    """Parser_v2 lexer token contract."""

    token_id: str
    raw_label: str
    normalized_label: str
    position_start: int
    position_end: int
    line_index: int
    column_index: int
    is_line_start: bool
    indentation_score: float
    candidate_types: tuple[CandidateType, ...]
    ordinal_by_type: dict[CandidateType, int]
    xref_context_features: dict[str, bool]
    layout_features: dict[str, LayoutFeatureValue]
    source_span: SourceSpan

    def __post_init__(self) -> None:
        if not self.token_id:
            raise ValueError("token_id cannot be empty")
        if self.position_start < 0:
            raise ValueError("position_start must be >= 0")
        if self.position_end <= self.position_start:
            raise ValueError("position_end must be > position_start")
        if self.line_index < 0 or self.column_index < 0:
            raise ValueError("line_index/column_index must be >= 0")
        if not 0.0 <= self.indentation_score <= 1.0:
            raise ValueError("indentation_score must be in [0.0, 1.0]")
        if not self.candidate_types:
            raise ValueError("candidate_types cannot be empty")
        for level_type in self.candidate_types:
            if level_type not in self.ordinal_by_type:
                raise ValueError(f"ordinal missing for candidate type {level_type!r}")
