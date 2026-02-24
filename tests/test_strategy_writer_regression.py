"""Regression tests for strategy_writer text-source behavior."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb


def _load_strategy_writer_module() -> object:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "strategy_writer.py"
    spec = importlib.util.spec_from_file_location("strategy_writer", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestStrategyWriterRegression:
    def test_prefers_section_text_for_regression_matching(self) -> None:
        mod = _load_strategy_writer_module()

        con = duckdb.connect(":memory:")
        con.execute(
            """
            CREATE TABLE documents (
                doc_id VARCHAR,
                template_family VARCHAR,
                text VARCHAR
            )
            """
        )
        con.execute(
            """
            CREATE TABLE section_text (
                doc_id VARCHAR,
                section_number VARCHAR,
                text VARCHAR
            )
            """
        )

        con.execute(
            """
            INSERT INTO documents VALUES
            ('d1', 'kirkland', 'this should not match'),
            ('d2', 'cahill', 'this should not match either')
            """
        )
        con.execute(
            """
            INSERT INTO section_text VALUES
            ('d1', '7.01', 'Limitation on Indebtedness'),
            ('d2', '7.01', 'No debt covenant match in this section')
            """
        )

        strategy = {"heading_patterns": ["Limitation on Indebtedness"]}
        out = mod.run_strategy_against_docs(strategy, con, "debt_capacity.indebtedness")
        con.close()

        assert out["kirkland"]["hits"] == 1
        assert out["kirkland"]["total"] == 1
        assert out["cahill"]["hits"] == 0
        assert out["cahill"]["total"] == 1

    def test_validate_regression_results_rejects_empty_outputs(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason = mod.validate_regression_results({}, {"all": {"total": 1, "hits": 0}})
        assert ok is False
        assert "Current strategy produced no evaluable" in reason

        ok, reason = mod.validate_regression_results({"all": {"total": 1, "hits": 1}}, {})
        assert ok is False
        assert "Updated strategy produced no evaluable" in reason

    def test_validate_regression_results_accepts_nonempty_groups(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason = mod.validate_regression_results(
            {"kirkland": {"total": 10, "hits": 8, "hit_rate": 0.8}},
            {"kirkland": {"total": 10, "hits": 9, "hit_rate": 0.9}},
        )
        assert ok is True
        assert reason == ""

    def test_v2_gate_rejects_missing_policies(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason = mod.ensure_strategy_v2_gates({"acceptance_policy_version": "v2"})
        assert ok is False
        assert "outlier_policy" in reason

    def test_v2_gate_allows_populated_policies(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason = mod.ensure_strategy_v2_gates(
            {
                "acceptance_policy_version": "v2",
                "outlier_policy": {"max_outlier_rate": 0.01},
                "template_stability_policy": {"max_template_variance": 0.1},
                "did_not_find_policy": {"min_coverage": 0.9},
            }
        )
        assert ok is True
        assert reason == ""

    def test_v2_gate_rejects_missing_did_not_find_policy(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason = mod.ensure_strategy_v2_gates(
            {
                "acceptance_policy_version": "v2",
                "outlier_policy": {"max_outlier_rate": 0.01},
                "template_stability_policy": {"max_template_variance": 0.1},
            }
        )
        assert ok is False
        assert "did_not_find_policy" in reason

    def test_v1_gate_skips_policies(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason = mod.ensure_strategy_v2_gates({})
        assert ok is True
        assert reason == ""

    def test_template_stability_rejects_low_group_hit_rate(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason, details = mod.evaluate_template_stability_policy(
            {
                "kirkland": {"hits": 9, "total": 10, "hit_rate": 0.9},
                "cahill": {"hits": 2, "total": 10, "hit_rate": 0.2},
            },
            {
                "min_group_size": 5,
                "min_groups": 2,
                "min_group_hit_rate": 0.5,
            },
        )
        assert ok is False
        assert "min_group_hit_rate" in reason
        assert details["min_group_hit_rate_failures"][0]["group"] == "cahill"

    def test_template_stability_accepts_balanced_groups(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason, details = mod.evaluate_template_stability_policy(
            {
                "kirkland": {"hits": 8, "total": 10, "hit_rate": 0.8},
                "cahill": {"hits": 7, "total": 10, "hit_rate": 0.7},
            },
            {
                "min_group_size": 5,
                "min_groups": 2,
                "min_group_hit_rate": 0.6,
                "max_group_hit_rate_gap": 0.2,
            },
        )
        assert ok is True
        assert reason == ""
        assert details["enforced"] is True

    def test_outlier_policy_rejects_limit_breach(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason, details = mod.evaluate_outlier_summary_against_policy(
            {
                "outlier_rate": 0.2,
                "high_risk_rate": 0.08,
                "review_risk_rate": 0.05,
                "evaluated_hits": 100,
                "thresholds": {"high_risk": 0.75},
            },
            {"max_outlier_rate": 0.1},
        )
        assert ok is False
        assert "outlier_rate" in reason
        assert details["violations"]

    def test_outlier_policy_accepts_when_within_limits(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason, details = mod.evaluate_outlier_summary_against_policy(
            {
                "outlier_rate": 0.04,
                "high_risk_rate": 0.01,
                "review_risk_rate": 0.02,
                "evaluated_hits": 100,
                "thresholds": {"high_risk": 0.75},
            },
            {"max_outlier_rate": 0.1, "max_high_risk_rate": 0.05},
        )
        assert ok is True
        assert reason == ""
        assert details["violations"] == []

    def test_did_not_find_policy_rejects_limit_breach(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason, details = mod.evaluate_did_not_find_summary_against_policy(
            {
                "coverage": 0.72,
                "near_miss_rate": 0.28,
                "near_miss_count": 18,
                "near_miss_cutoff": 0.24,
                "passes_policy": False,
            },
            {
                "min_coverage": 0.90,
                "max_near_miss_rate": 0.15,
                "max_near_miss_count": 10,
            },
        )
        assert ok is False
        assert "Did-not-find policy gate failed" in reason
        assert details["violations"]

    def test_did_not_find_policy_accepts_when_within_limits(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason, details = mod.evaluate_did_not_find_summary_against_policy(
            {
                "coverage": 0.95,
                "near_miss_rate": 0.04,
                "near_miss_count": 2,
                "near_miss_cutoff": 0.24,
                "passes_policy": True,
            },
            {
                "min_coverage": 0.90,
                "max_near_miss_rate": 0.15,
                "max_near_miss_count": 10,
            },
        )
        assert ok is True
        assert reason == ""
        assert details["violations"] == []

    def test_llm_judge_gate_rejects_low_precision(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason, details = mod.evaluate_llm_judge_report(
            {
                "schema_version": "llm_judge_v1",
                "concept_id": "debt_capacity.indebtedness",
                "n_sampled": 20,
                "precision_estimate": 0.70,
                "weighted_precision_estimate": 0.75,
                "correct": 14,
                "partial": 2,
                "wrong": 4,
            },
            concept_id="debt_capacity.indebtedness",
            min_precision=0.8,
            min_samples=20,
            precision_mode="strict",
        )
        assert ok is False
        assert "below minimum" in reason
        assert details["selected_precision"] == 0.7

    def test_llm_judge_gate_accepts_weighted_precision(self) -> None:
        mod = _load_strategy_writer_module()
        ok, reason, details = mod.evaluate_llm_judge_report(
            {
                "schema_version": "llm_judge_v1",
                "concept_id": "debt_capacity.indebtedness",
                "n_sampled": 20,
                "precision_estimate": 0.75,
                "weighted_precision_estimate": 0.84,
                "correct": 15,
                "partial": 4,
                "wrong": 1,
            },
            concept_id="debt_capacity.indebtedness",
            min_precision=0.8,
            min_samples=20,
            precision_mode="weighted",
        )
        assert ok is True
        assert reason == ""
        assert details["selected_precision_field"] == "weighted_precision_estimate"
