"""Tests for agent.strategy module."""
import tempfile
from pathlib import Path

from agent.strategy import (
    Strategy,
    load_strategy,
    merge_strategies,
    next_version,
    save_strategy,
    strategy_from_dict,
    strategy_to_dict,
)


def _make_strategy() -> Strategy:
    return Strategy(
        concept_id="debt_capacity.indebtedness",
        concept_name="Indebtedness",
        family="indebtedness",
        heading_patterns=("Indebtedness", "Limitation on Indebtedness"),
        keyword_anchors=("borrower", "indebtedness"),
        version=1,
    )


class TestStrategyRoundTrip:
    def test_to_dict_and_back(self) -> None:
        s = _make_strategy()
        d = strategy_to_dict(s)
        restored = strategy_from_dict(d)
        assert restored.concept_id == s.concept_id
        assert restored.heading_patterns == s.heading_patterns
        assert restored.keyword_anchors == s.keyword_anchors

    def test_dict_has_lists_not_tuples(self) -> None:
        s = _make_strategy()
        d = strategy_to_dict(s)
        assert isinstance(d["heading_patterns"], list)
        assert isinstance(d["keyword_anchors"], list)

    def test_save_and_load(self) -> None:
        s = _make_strategy()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strategy.json"
            save_strategy(s, path)
            assert path.exists()
            loaded = load_strategy(path)
            assert loaded.concept_id == s.concept_id
            assert loaded.heading_patterns == s.heading_patterns


class TestNextVersion:
    def test_increments_version(self) -> None:
        s = _make_strategy()
        v2 = next_version(s, note="Added new heading")
        assert v2.version == 2
        assert "Added new heading" in v2.update_notes

    def test_preserves_fields(self) -> None:
        s = _make_strategy()
        v2 = next_version(s)
        assert v2.concept_id == s.concept_id
        assert v2.heading_patterns == s.heading_patterns

    def test_sets_timestamp(self) -> None:
        s = _make_strategy()
        v2 = next_version(s)
        assert v2.last_updated != ""


class TestMergeStrategies:
    def test_partial_update(self) -> None:
        s = _make_strategy()
        merged = merge_strategies(s, {"heading_hit_rate": 0.85})
        assert merged.heading_hit_rate == 0.85
        assert merged.concept_id == s.concept_id

    def test_ignores_unknown_keys(self) -> None:
        s = _make_strategy()
        merged = merge_strategies(s, {"nonexistent_field": "ignored"})
        assert merged.concept_id == s.concept_id


class TestStrategyFrozen:
    def test_immutable(self) -> None:
        s = _make_strategy()
        try:
            s.concept_id = "modified"  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass
