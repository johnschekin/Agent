"""Tests for legacy API deprecation in dashboard server."""
from __future__ import annotations

from dashboard.api import server as dashboard_server


def test_legacy_prefixes_are_declared() -> None:
    prefixes = dashboard_server._LEGACY_API_PREFIXES
    assert "/api/jobs" in prefixes
    assert "/api/strategies" in prefixes
    assert "/api/review" in prefixes
    assert "/api/ml/review-queue" in prefixes
    assert "/api/ml/heading-clusters" in prefixes
    assert "/api/ml/concepts-with-evidence" in prefixes


def test_legacy_replacement_mapping() -> None:
    assert dashboard_server._legacy_api_replacement("/api/jobs") == "/api/links/intelligence/ops"
    assert dashboard_server._legacy_api_replacement("/api/jobs/submit") == "/api/links/intelligence/ops"
    assert dashboard_server._legacy_api_replacement("/api/strategies") == "/api/links/rules"
    assert dashboard_server._legacy_api_replacement("/api/strategies/stats") == "/api/links/rules"
    assert dashboard_server._legacy_api_replacement("/api/review/evidence") == "/api/links/intelligence/evidence"
    assert dashboard_server._legacy_api_replacement("/api/ml/review-queue") == "/api/links/intelligence/signals"


def test_legacy_handler_functions_removed() -> None:
    removed = [
        "submit_job",
        "get_job_status",
        "cancel_job",
        "job_stream",
        "list_strategies",
        "strategy_stats",
        "get_strategy",
        "get_latest_judge_report",
        "review_strategy_timeline",
        "review_evidence",
        "review_coverage_heatmap",
        "review_judge_history",
        "review_agent_activity",
        "ml_review_queue",
        "ml_heading_clusters",
        "ml_concepts_with_evidence",
    ]
    for name in removed:
        assert not hasattr(dashboard_server, name), f"expected legacy handler removed: {name}"
