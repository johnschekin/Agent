"""Tests for unified confidence runtime helpers."""

from agent.confidence import (
    build_confidence_breakdown,
    passes_component_mins,
    resolve_components,
    weighted_confidence_score,
)


def test_confidence_component_resolution() -> None:
    components = resolve_components(
        score=0.82,
        score_margin=0.20,
        active_channels=("heading", "keyword"),
        heading_hit=True,
        keyword_hit=True,
        dna_hit=False,
        keyword_hit_count=2,
    )
    assert 0.0 <= components["score"] <= 1.0
    assert components["heading"] == 1.0
    assert components["keyword"] > 0


def test_weighted_confidence_score() -> None:
    score = weighted_confidence_score(
        {"score": 0.9, "margin": 0.6, "channels": 0.8},
        policy={"weights": {"score": 0.4, "margin": 0.3, "channels": 0.3}},
    )
    assert 0.0 <= score <= 1.0


def test_breakdown_and_min_checks() -> None:
    breakdown = build_confidence_breakdown(
        score=0.8,
        score_margin=0.15,
        active_channels=("heading", "keyword", "dna"),
        heading_hit=True,
        keyword_hit=True,
        dna_hit=True,
        keyword_hit_count=2,
        policy={"weights": {"score": 0.5, "margin": 0.2, "channels": 0.3}},
    )
    assert passes_component_mins(breakdown, {"heading": 1.0}) is True
    assert passes_component_mins(breakdown, {"score": 0.95}) is False

