"""Boolean scope parity helpers for proviso-aware matching.

This module provides a lightweight approximation of round9_boolean_parity:
- classify scope tendency (BROAD/NARROW/BALANCED/UNKNOWN)
- expose operator counts and depth-like signal for policy gates
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


PERMIT_PATTERNS: tuple[str, ...] = (
    r"\bexcept\b",
    r"\bunless\b",
    r"\bprovided that\b",
    r"\bmay\b",
    r"\bpermitted\b",
)
RESTRICT_PATTERNS: tuple[str, ...] = (
    r"\bshall not\b",
    r"\bmay not\b",
    r"\bprohibited\b",
    r"\bmust not\b",
    r"\bno\b",
)


@dataclass(frozen=True, slots=True)
class ScopeParityResult:
    label: str
    permit_count: int
    restrict_count: int
    operator_count: int
    estimated_depth: int


def _pattern_occurrences(text: str, patterns: tuple[str, ...]) -> int:
    count = 0
    for pat in patterns:
        try:
            count += len(re.findall(pat, text, flags=re.IGNORECASE))
        except re.error:
            count += text.lower().count(pat.lower())
    return count


def compute_scope_parity(text: str) -> ScopeParityResult:
    """Compute parity-style scope signal for clause/section text."""
    text_lower = (text or "").lower()
    permit_count = _pattern_occurrences(text_lower, PERMIT_PATTERNS)
    restrict_count = _pattern_occurrences(text_lower, RESTRICT_PATTERNS)
    operator_count = permit_count + restrict_count

    if operator_count == 0:
        label = "UNKNOWN"
    elif restrict_count >= permit_count + 2:
        label = "NARROW"
    elif permit_count >= restrict_count + 2:
        label = "BROAD"
    else:
        label = "BALANCED"

    estimated_depth = min(8, operator_count)
    return ScopeParityResult(
        label=label,
        permit_count=permit_count,
        restrict_count=restrict_count,
        operator_count=operator_count,
        estimated_depth=estimated_depth,
    )


def passes_operator_requirements(
    result: ScopeParityResult,
    requirements: dict[str, Any],
) -> bool:
    """Evaluate strategy boolean_operator_requirements against parity result."""
    if not requirements:
        return True

    min_operator_count = int(requirements.get("min_operator_count", 0) or 0)
    min_permit_count = int(requirements.get("min_permit_count", 0) or 0)
    min_restrict_count = int(requirements.get("min_restrict_count", 0) or 0)
    require_both_types = bool(requirements.get("require_both_types", False))

    if result.operator_count < min_operator_count:
        return False
    if result.permit_count < min_permit_count:
        return False
    if result.restrict_count < min_restrict_count:
        return False
    if require_both_types and (result.permit_count <= 0 or result.restrict_count <= 0):
        return False
    return True

