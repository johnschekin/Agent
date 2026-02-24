"""Materialized section/clause feature builders for corpus ingestion."""
from __future__ import annotations

import json
from typing import Any

from agent.definition_types import classify_definition_text
from agent.preemption import summarize_preemption
from agent.scope_parity import compute_scope_parity


def build_section_feature(
    *,
    doc_id: str,
    section_number: str,
    heading: str,
    text: str,
    char_start: int,
    char_end: int,
    article_num: int,
    word_count: int,
) -> dict[str, Any]:
    """Build a strategy-agnostic section feature record."""
    text_lower = text.lower() if text else ""
    parity = compute_scope_parity(text_lower)
    preemption = summarize_preemption(text_lower)
    definition_types = classify_definition_text(text_lower)
    return {
        "doc_id": doc_id,
        "section_number": section_number,
        "article_num": int(article_num),
        "char_start": int(char_start),
        "char_end": int(char_end),
        "word_count": int(word_count),
        "char_count": max(0, int(char_end) - int(char_start)),
        "heading_lower": heading.lower() if heading else "",
        "scope_label": parity.label,
        "scope_operator_count": parity.operator_count,
        "scope_permit_count": parity.permit_count,
        "scope_restrict_count": parity.restrict_count,
        "scope_estimated_depth": parity.estimated_depth,
        "preemption_override_count": preemption.override_count,
        "preemption_yield_count": preemption.yield_count,
        "preemption_estimated_depth": preemption.estimated_depth,
        "preemption_has": preemption.has_preemption,
        "preemption_edge_count": preemption.edge_count,
        "definition_types": json.dumps(sorted(definition_types.detected_types)),
        "definition_type_primary": definition_types.primary_type,
        "definition_type_confidence": definition_types.confidence,
    }


def build_clause_feature(
    *,
    doc_id: str,
    section_number: str,
    clause_id: str,
    depth: int,
    level_type: str,
    clause_text: str,
    parse_confidence: float,
    is_structural: bool,
) -> dict[str, Any]:
    """Build a strategy-agnostic clause feature record."""
    text = clause_text or ""
    token_count = len(text.split()) if text else 0
    return {
        "doc_id": doc_id,
        "section_number": section_number,
        "clause_id": clause_id,
        "depth": int(depth),
        "level_type": str(level_type),
        "token_count": int(token_count),
        "char_count": len(text),
        "has_digits": any(ch.isdigit() for ch in text),
        "parse_confidence": float(parse_confidence),
        "is_structural": bool(is_structural),
    }
