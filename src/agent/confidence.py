"""Unified confidence helpers for strategy evaluation/runtime.

A lightweight confidence service inspired by Neutron's unified-confidence
pattern. It exposes:
- normalized component computation
- weighted score aggregation
- component threshold checks
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_WEIGHTS: dict[str, float] = {
    "score": 0.5,
    "margin": 0.2,
    "channels": 0.3,
}


@dataclass(frozen=True, slots=True)
class ConfidenceBreakdown:
    score: float
    margin: float
    channels: float
    heading: float
    keyword: float
    dna: float
    final: float

    def as_dict(self) -> dict[str, float]:
        return {
            "score": self.score,
            "margin": self.margin,
            "channels": self.channels,
            "heading": self.heading,
            "keyword": self.keyword,
            "dna": self.dna,
            "final": self.final,
        }


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def resolve_components(
    *,
    score: float,
    score_margin: float,
    active_channels: tuple[str, ...],
    heading_hit: bool,
    keyword_hit: bool,
    dna_hit: bool,
    keyword_hit_count: int,
) -> dict[str, float]:
    """Compute normalized confidence components."""
    heading_component = 1.0 if heading_hit else 0.0
    keyword_component = (
        min(1.0, max(0, int(keyword_hit_count)) / 3.0) if keyword_hit else 0.0
    )
    dna_component = 1.0 if dna_hit else 0.0
    channels_component = min(1.0, len(active_channels) / 3.0)
    margin_component = min(1.0, max(0.0, score_margin) / 0.40)
    return {
        "score": _bounded(score),
        "margin": _bounded(margin_component),
        "channels": _bounded(channels_component),
        "heading": _bounded(heading_component),
        "keyword": _bounded(keyword_component),
        "dna": _bounded(dna_component),
    }


def weighted_confidence_score(
    components: dict[str, float],
    policy: dict[str, Any] | None = None,
) -> float:
    """Compute weighted confidence score using policy override weights."""
    policy = policy or {}
    weights = dict(DEFAULT_WEIGHTS)
    configured = policy.get("weights", {})
    if isinstance(configured, dict):
        for key in ("score", "margin", "channels"):
            if key in configured:
                try:
                    weights[key] = max(0.0, float(configured[key]))
                except (TypeError, ValueError):
                    continue

    total_weight = sum(weights.values())
    if total_weight <= 1e-9:
        return _bounded(components.get("score", 0.0))
    value = 0.0
    for key, weight in weights.items():
        value += float(components.get(key, 0.0)) * weight
    return _bounded(value / total_weight)


def build_confidence_breakdown(
    *,
    score: float,
    score_margin: float,
    active_channels: tuple[str, ...],
    heading_hit: bool,
    keyword_hit: bool,
    dna_hit: bool,
    keyword_hit_count: int,
    policy: dict[str, Any] | None = None,
) -> ConfidenceBreakdown:
    components = resolve_components(
        score=score,
        score_margin=score_margin,
        active_channels=active_channels,
        heading_hit=heading_hit,
        keyword_hit=keyword_hit,
        dna_hit=dna_hit,
        keyword_hit_count=keyword_hit_count,
    )
    final_score = weighted_confidence_score(components, policy=policy)
    return ConfidenceBreakdown(
        score=round(components["score"], 4),
        margin=round(components["margin"], 4),
        channels=round(components["channels"], 4),
        heading=round(components["heading"], 4),
        keyword=round(components["keyword"], 4),
        dna=round(components["dna"], 4),
        final=round(final_score, 4),
    )


def passes_component_mins(
    components: dict[str, float] | ConfidenceBreakdown,
    minimums: dict[str, float],
) -> bool:
    if not minimums:
        return True
    data = components.as_dict() if isinstance(components, ConfidenceBreakdown) else components
    for key, min_required in minimums.items():
        try:
            threshold = float(min_required)
        except (TypeError, ValueError):
            continue
        if float(data.get(key, 0.0)) < threshold:
            return False
    return True

