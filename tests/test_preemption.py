"""Tests for preemption/override utilities."""

from agent.preemption import (
    extract_preemption_edges,
    passes_preemption_requirements,
    summarize_preemption,
)


def test_preemption_summary_detects_markers() -> None:
    text = (
        "Notwithstanding Section 7.01, the Borrower may incur debt subject to Section 7.02."
    )
    summary = summarize_preemption(text)
    assert summary.override_count >= 1
    assert summary.yield_count >= 1
    assert summary.has_preemption is True


def test_preemption_edges_extract_reference() -> None:
    text = "Notwithstanding Section 7.01, the Borrower may incur debt."
    edges = extract_preemption_edges(text)
    assert edges
    assert edges[0].edge_type in {"override", "yield"}


def test_preemption_requirements_gate() -> None:
    summary = summarize_preemption(
        "Notwithstanding Section 7.01, subject to Section 7.02, the Borrower may act."
    )
    ok = passes_preemption_requirements(
        summary,
        {"require_both": True, "min_override_count": 1, "min_yield_count": 1},
    )
    assert ok is True

