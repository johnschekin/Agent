"""Preemption graph helpers (override/yield extraction).

This is a pragmatic baseline inspired by round9_preemption_dag:
- extract override/yield markers from text
- capture nearby section references
- summarize depth and edge counts for gating/diagnostics
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


OVERRIDE_PATTERNS: tuple[str, ...] = (
    r"\bnotwithstanding\b",
    r"\bwithout limiting\b",
    r"\bin lieu of\b",
)
YIELD_PATTERNS: tuple[str, ...] = (
    r"\bsubject to\b",
    r"\bexcept as provided\b",
    r"\bexcept as otherwise\b",
)
SECTION_REF_RE = re.compile(
    r"\b(?:section|clause|article)\s+([0-9IVXLCM]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PreemptionEdge:
    edge_type: str  # override | yield
    trigger_text: str
    reference: str
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class PreemptionSummary:
    override_count: int
    yield_count: int
    estimated_depth: int
    has_preemption: bool
    edge_count: int


def _pattern_matches(text: str, patterns: tuple[str, ...], edge_type: str) -> list[PreemptionEdge]:
    edges: list[PreemptionEdge] = []
    for pat in patterns:
        try:
            matches = re.finditer(pat, text, flags=re.IGNORECASE)
        except re.error:
            continue
        for m in matches:
            start = m.start()
            end = m.end()
            window = text[max(0, start - 120): min(len(text), end + 120)]
            ref_match = SECTION_REF_RE.search(window)
            reference = ref_match.group(1) if ref_match else ""
            edges.append(
                PreemptionEdge(
                    edge_type=edge_type,
                    trigger_text=text[start:end],
                    reference=reference,
                    char_start=start,
                    char_end=end,
                )
            )
    return edges


def extract_preemption_edges(text: str) -> list[PreemptionEdge]:
    """Extract override/yield edges from raw text."""
    src = text or ""
    edges: list[PreemptionEdge] = []
    edges.extend(_pattern_matches(src, OVERRIDE_PATTERNS, "override"))
    edges.extend(_pattern_matches(src, YIELD_PATTERNS, "yield"))
    edges.sort(key=lambda e: (e.char_start, e.edge_type))
    return edges


def summarize_preemption(text: str) -> PreemptionSummary:
    edges = extract_preemption_edges(text)
    override_count = sum(1 for e in edges if e.edge_type == "override")
    yield_count = sum(1 for e in edges if e.edge_type == "yield")
    estimated_depth = min(8, override_count + yield_count)
    return PreemptionSummary(
        override_count=override_count,
        yield_count=yield_count,
        estimated_depth=estimated_depth,
        has_preemption=(override_count + yield_count) > 0,
        edge_count=len(edges),
    )


def passes_preemption_requirements(
    summary: PreemptionSummary,
    requirements: dict[str, Any],
) -> bool:
    """Evaluate strategy preemption_requirements against extracted summary."""
    if not requirements:
        return True

    if bool(requirements.get("require_override_or_yield", False)):
        if (summary.override_count + summary.yield_count) <= 0:
            return False
    min_override = int(requirements.get("min_override_count", 0) or 0)
    min_yield = int(requirements.get("min_yield_count", 0) or 0)
    if summary.override_count < min_override:
        return False
    if summary.yield_count < min_yield:
        return False
    if bool(requirements.get("require_both", False)):
        if summary.override_count <= 0 or summary.yield_count <= 0:
            return False
    return True

