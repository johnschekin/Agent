"""Unit tests for pattern_tester strategy gate wiring."""
from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path
from typing import Any

from agent.strategy import Strategy


def _load_pattern_tester_module() -> Any:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "pattern_tester.py"
    spec = importlib.util.spec_from_file_location("pattern_tester", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _base_strategy(**updates: Any) -> Strategy:
    base = Strategy(
        concept_id="debt_capacity.indebtedness",
        concept_name="Indebtedness",
        family="indebtedness",
        heading_patterns=("Limitation on Indebtedness",),
        keyword_anchors=("indebtedness",),
    )
    return replace(base, **updates)


def _base_kwargs() -> dict[str, Any]:
    return {
        "score": 0.92,
        "score_margin": 0.35,
        "method": "heading",
        "heading": "Limitation on Indebtedness",
        "text_lower": (
            "the borrower shall not incur indebtedness except as permitted. "
            "notwithstanding the foregoing, subject to section 7.02."
        ),
        "section_number": "7.01",
        "article_num": 7,
        "template_family": "kirkland",
        "section_word_count": 120,
        "keyword_hit_count": 3,
        "active_channels": ("heading", "keyword"),
        "signal_details": {
            "heading_hit": True,
            "keyword_hit": True,
            "dna_hit": False,
            "active_channels": ("heading", "keyword"),
            "signal_channel_count": 2,
            "negative_keyword_hits": 0,
            "negative_dna_hit": False,
        },
        "detected_functional_areas": {"negative_covenants"},
        "detected_definition_types": {"FORMULAIC", "HYBRID"},
        "definition_dependency_overlap": 0.75,
        "scope_parity": {
            "label": "NARROW",
            "permit_count": 1,
            "restrict_count": 3,
            "operator_count": 4,
        },
        "preemption_features": {
            "override_count": 1,
            "yield_count": 1,
            "estimated_depth": 2,
            "has_preemption": True,
        },
        "structural_fingerprint_tokens": {
            "template:kirkland",
            "article:7",
            "section_prefix:7",
        },
        "strict_keyword_gate": False,
        "hit_threshold": 0.3,
        "min_keyword_hits": 2,
    }


class TestPatternTesterGates:
    def test_canonical_heading_gate_rejects_mismatch(self) -> None:
        mod = _load_pattern_tester_module()
        strategy = _base_strategy(canonical_heading_labels=("leverage_ratio",))
        kwargs = _base_kwargs()
        kwargs["heading"] = "Investments"
        assert mod.should_accept_hit(strategy=strategy, **kwargs) is False

    def test_definition_type_allowlist_rejects_non_matching(self) -> None:
        mod = _load_pattern_tester_module()
        strategy = _base_strategy(definition_type_allowlist=("ENUMERATIVE",))
        kwargs = _base_kwargs()
        kwargs["detected_definition_types"] = {"DIRECT"}
        assert mod.should_accept_hit(strategy=strategy, **kwargs) is False

    def test_scope_parity_block_rejects_blocked_label(self) -> None:
        mod = _load_pattern_tester_module()
        strategy = _base_strategy(scope_parity_block=("BROAD",))
        kwargs = _base_kwargs()
        kwargs["scope_parity"] = {
            "label": "BROAD",
            "permit_count": 4,
            "restrict_count": 0,
            "operator_count": 4,
        }
        assert mod.should_accept_hit(strategy=strategy, **kwargs) is False

    def test_preemption_requirement_rejects_missing(self) -> None:
        mod = _load_pattern_tester_module()
        strategy = _base_strategy(preemption_requirements={"require_override_or_yield": True})
        kwargs = _base_kwargs()
        kwargs["preemption_features"] = {
            "override_count": 0,
            "yield_count": 0,
            "estimated_depth": 0,
            "has_preemption": False,
        }
        assert mod.should_accept_hit(strategy=strategy, **kwargs) is False

    def test_confidence_policy_min_final_rejects_low_components(self) -> None:
        mod = _load_pattern_tester_module()
        strategy = _base_strategy(
            confidence_policy={"min_final": 0.85},
            confidence_components_min={"heading": 1.0},
        )
        kwargs = _base_kwargs()
        kwargs["score"] = 0.55
        kwargs["score_margin"] = 0.05
        kwargs["signal_details"]["heading_hit"] = False
        kwargs["active_channels"] = ("keyword",)
        assert mod.should_accept_hit(strategy=strategy, **kwargs) is False

    def test_template_and_fingerprint_constraints_can_accept(self) -> None:
        mod = _load_pattern_tester_module()
        strategy = _base_strategy(
            template_module_constraints={
                "allowed_template_families": ["kirkland"],
                "required_modules": ["negative_covenants"],
            },
            structural_fingerprint_allowlist=("template:kirkland",),
        )
        kwargs = _base_kwargs()
        assert mod.should_accept_hit(strategy=strategy, **kwargs) is True

    def test_did_not_find_policy_reports_violation(self) -> None:
        mod = _load_pattern_tester_module()
        summary = mod._evaluate_did_not_find_policy(
            policy={"min_coverage": 0.9, "max_near_miss_rate": 0.1},
            total_docs=10,
            docs_with_sections=6,
            misses=[
                {"best_score": 0.35},
                {"best_score": 0.31},
                {"best_score": 0.02},
            ],
            hit_threshold=0.3,
        )
        assert summary["passes_policy"] is False
        assert "min_coverage" in summary["violations"]

    def test_outlier_summary_includes_structural_rarity_signals(self) -> None:
        mod = _load_pattern_tester_module()
        strategy = _base_strategy()
        hits = [
            {
                "doc_id": "d1",
                "section": "7.01",
                "heading": "Limitation on Indebtedness",
                "article_num": 7,
                "template_family": "cluster_001",
                "score": 0.91,
                "score_margin": 0.22,
                "match_method": "heading",
                "section_word_count": 110,
                "signal_channels": 2,
            },
            {
                "doc_id": "d2",
                "section": "7.01",
                "heading": "Limitation on Indebtedness",
                "article_num": 7,
                "template_family": "cluster_001",
                "score": 0.89,
                "score_margin": 0.20,
                "match_method": "heading",
                "section_word_count": 112,
                "signal_channels": 2,
            },
            {
                "doc_id": "d3",
                "section": "9.03",
                "heading": "Exotic Heading",
                "article_num": 9,
                "template_family": "cluster_999",
                "score": 0.45,
                "score_margin": 0.03,
                "match_method": "keyword",
                "section_word_count": 350,
                "signal_channels": 1,
            },
        ]

        outlier_summary = mod._compute_outliers(hits, strategy=strategy)
        assert outlier_summary["evaluated_hits"] == 3
        assert hits[2]["outlier"]["risk_components"]["heading_rarity"] > 0.0
        assert hits[2]["outlier"]["risk_components"]["article_rarity"] > 0.0
        assert hits[2]["outlier"]["risk_components"]["template_rarity"] > 0.0
        assert "heading_rare" in hits[2]["outlier"]["flags"]
        assert "article_rare" in hits[2]["outlier"]["flags"]
        assert "template_rare" in hits[2]["outlier"]["flags"]
