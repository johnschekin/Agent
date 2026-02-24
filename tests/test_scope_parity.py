"""Tests for scope parity engine."""

from agent.scope_parity import compute_scope_parity, passes_operator_requirements


def test_scope_parity_unknown() -> None:
    result = compute_scope_parity("The Borrower shall deliver financial statements.")
    assert result.label == "UNKNOWN"
    assert result.operator_count == 0


def test_scope_parity_balanced() -> None:
    text = "The Borrower shall not incur debt, except as provided that it may incur ratio debt."
    result = compute_scope_parity(text)
    assert result.operator_count >= 2
    assert result.label in {"BALANCED", "NARROW", "BROAD"}


def test_scope_operator_requirements() -> None:
    text = "Except as provided that the Borrower may act, the Borrower shall not act."
    result = compute_scope_parity(text)
    ok = passes_operator_requirements(
        result,
        {
            "min_operator_count": 2,
            "require_both_types": True,
        },
    )
    assert ok is True

