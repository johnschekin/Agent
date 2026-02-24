"""Tests for agent.strategy module."""
import tempfile
from pathlib import Path

from agent.strategy import (
    Strategy,
    load_strategy,
    load_strategy_with_views,
    merge_strategies,
    next_version,
    resolve_strategy_dict,
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

    def test_v2_policy_fields_round_trip(self) -> None:
        s = Strategy(
            concept_id="debt_capacity.indebtedness",
            concept_name="Indebtedness",
            family="indebtedness",
            heading_patterns=("Indebtedness",),
            keyword_anchors=("incur",),
            negative_heading_patterns=("Classification of Loans and Borrowings",),
            min_score_by_method={"heading": 0.9, "composite": 0.85},
            outlier_policy={"max_high_risk_rate": 0.01, "max_outlier_rate": 0.05},
            acceptance_policy_version="v2",
        )
        d = strategy_to_dict(s)
        restored = strategy_from_dict(d)
        assert restored.negative_heading_patterns == ("Classification of Loans and Borrowings",)
        assert restored.min_score_by_method["heading"] == 0.9
        assert restored.outlier_policy["max_outlier_rate"] == 0.05
        assert restored.acceptance_policy_version == "v2"

    def test_strategy_from_dict_ignores_unknown_keys(self) -> None:
        d = strategy_to_dict(_make_strategy())
        d["_meta"] = {"version": 7}
        restored = strategy_from_dict(d)
        assert restored.concept_id == "debt_capacity.indebtedness"

    def test_repurpose_fields_round_trip(self) -> None:
        s = Strategy(
            concept_id="debt_capacity.indebtedness",
            concept_name="Indebtedness",
            family="indebtedness",
            heading_patterns=("Indebtedness",),
            keyword_anchors=("incur",),
            profile_type="concept_advanced",
            canonical_heading_labels=("limitation_on_indebtedness",),
            functional_area_hints=("negative_covenants",),
            definition_type_allowlist=("FORMULAIC", "HYBRID"),
            definition_type_blocklist=("TABLE_REGULATORY",),
            min_definition_dependency_overlap=0.2,
            scope_parity_allow=("NARROW",),
            scope_parity_block=("BROAD",),
            boolean_operator_requirements={"min_operator_count": 2},
            preemption_requirements={"require_override_or_yield": True},
            max_preemption_depth=3,
            template_module_constraints={"required_modules": ["negative_covenants"]},
            structural_fingerprint_allowlist=("fp_a",),
            structural_fingerprint_blocklist=("fp_noise",),
            confidence_policy={"min_final": 0.8},
            confidence_components_min={"heading": 0.7, "keyword": 0.5},
            did_not_find_policy={"min_coverage": 0.9},
        )
        d = strategy_to_dict(s)
        restored = strategy_from_dict(d)
        assert restored.profile_type == "concept_advanced"
        assert restored.canonical_heading_labels == ("limitation_on_indebtedness",)
        assert restored.definition_type_allowlist == ("FORMULAIC", "HYBRID")
        assert restored.scope_parity_block == ("BROAD",)
        assert restored.max_preemption_depth == 3
        assert restored.confidence_components_min["heading"] == 0.7
        assert restored.did_not_find_policy["min_coverage"] == 0.9

    def test_legacy_strategy_dict_gets_new_defaults(self) -> None:
        legacy = {
            "concept_id": "debt_capacity.indebtedness",
            "concept_name": "Indebtedness",
            "family": "indebtedness",
            "heading_patterns": ["Indebtedness"],
            "keyword_anchors": ["incur", "debt"],
            "version": 2,
            "validation_status": "bootstrap",
        }
        restored = strategy_from_dict(legacy)
        assert restored.concept_id == "debt_capacity.indebtedness"
        assert restored.canonical_heading_labels == ()
        assert restored.definition_type_allowlist == ()
        assert restored.min_definition_dependency_overlap == 0.0
        assert restored.scope_parity_allow == ()
        assert restored.preemption_requirements == {}
        assert restored.template_module_constraints == {}
        assert restored.structural_fingerprint_allowlist == ()
        assert restored.confidence_policy == {}
        assert restored.confidence_components_min == {}
        assert restored.did_not_find_policy == {}
        assert restored.profile_type == "concept_standard"
        assert restored.inherits_from is None

    def test_invalid_profile_type_defaults_to_standard(self) -> None:
        legacy = {
            "concept_id": "debt_capacity.indebtedness",
            "concept_name": "Indebtedness",
            "family": "indebtedness",
            "heading_patterns": ["Indebtedness"],
            "keyword_anchors": ["incur", "debt"],
            "profile_type": "unknown_profile",
        }
        restored = strategy_from_dict(legacy)
        assert restored.profile_type == "concept_standard"

    def test_template_overrides_dict_round_trip(self) -> None:
        s = Strategy(
            concept_id="debt_capacity.indebtedness",
            concept_name="Indebtedness",
            family="indebtedness",
            heading_patterns=("Indebtedness",),
            keyword_anchors=("incur",),
            template_overrides={
                "cahill": {"heading_patterns": ["Limitation on Debt"]},
                "kirkland": {"min_score_margin": 0.05},
            },
        )
        d = strategy_to_dict(s)
        restored = strategy_from_dict(d)
        assert restored.template_overrides["cahill"]["heading_patterns"] == [
            "Limitation on Debt"
        ]
        assert restored.template_overrides["kirkland"]["min_score_margin"] == 0.05

    def test_template_overrides_legacy_pair_format_is_supported(self) -> None:
        legacy = {
            "concept_id": "debt_capacity.indebtedness",
            "concept_name": "Indebtedness",
            "family": "indebtedness",
            "heading_patterns": ["Indebtedness"],
            "keyword_anchors": ["incur"],
            "template_overrides": [
                ["cahill.heading_patterns", "[\"Limitation on Debt\"]"],
                ["kirkland.min_score_margin", "0.05"],
            ],
        }
        restored = strategy_from_dict(legacy)
        assert restored.template_overrides["cahill"]["heading_patterns"] == [
            "Limitation on Debt"
        ]
        assert restored.template_overrides["kirkland"]["min_score_margin"] == 0.05

    def test_load_strategy_with_inheritance_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parent_path = root / "debt_capacity.indebtedness_v001.json"
            parent_path.write_text(
                """
{
  "concept_id": "debt_capacity.indebtedness",
  "concept_name": "Indebtedness",
  "family": "indebtedness",
  "profile_type": "family_core",
  "heading_patterns": ["Limitation on Indebtedness"],
  "keyword_anchors": ["indebtedness", "debt"],
  "concept_specific_keywords": ["permitted indebtedness"]
}
                """.strip()
            )
            child_path = root / "debt_capacity.indebtedness.general_basket_v001.json"
            child_path.write_text(
                """
{
  "concept_id": "debt_capacity.indebtedness.general_basket",
  "concept_name": "General Basket",
  "family": "indebtedness",
  "profile_type": "concept_standard",
  "inherits_from": "debt_capacity.indebtedness_v001.json",
  "concept_specific_keywords": ["general basket"]
}
                """.strip()
            )
            loaded = load_strategy(child_path)
            assert loaded.heading_patterns == ("Limitation on Indebtedness",)
            assert loaded.keyword_anchors == ("indebtedness", "debt")
            assert loaded.concept_specific_keywords == ("general basket",)
            assert loaded.inherits_from == "debt_capacity.indebtedness_v001.json"

    def test_load_strategy_with_inheritance_by_concept_id_uses_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "debt_capacity.indebtedness_v001.json").write_text(
                """
{
  "concept_id": "debt_capacity.indebtedness",
  "concept_name": "Indebtedness",
  "family": "indebtedness",
  "heading_patterns": ["Old Parent"],
  "keyword_anchors": ["old"]
}
                """.strip()
            )
            (root / "debt_capacity.indebtedness_v003.json").write_text(
                """
{
  "concept_id": "debt_capacity.indebtedness",
  "concept_name": "Indebtedness",
  "family": "indebtedness",
  "heading_patterns": ["New Parent"],
  "keyword_anchors": ["new anchor"]
}
                """.strip()
            )
            child_path = root / "child_v001.json"
            child_path.write_text(
                """
{
  "concept_id": "debt_capacity.indebtedness.ratio_debt",
  "concept_name": "Ratio Debt",
  "family": "indebtedness",
  "inherits_from": "debt_capacity.indebtedness",
  "heading_patterns": ["Ratio Debt"]
}
                """.strip()
            )
            loaded = load_strategy(child_path)
            assert loaded.keyword_anchors == ("new anchor",)
            assert loaded.heading_patterns == ("Ratio Debt",)

    def test_resolve_strategy_dict_detects_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a_path = root / "a_v001.json"
            b_path = root / "b_v001.json"
            a_path.write_text(
                """
{"concept_id":"a","concept_name":"A","family":"a","heading_patterns":["A"],"keyword_anchors":["a"],"inherits_from":"b_v001.json"}
                """.strip()
            )
            b_path.write_text(
                """
{"concept_id":"b","concept_name":"B","family":"b","heading_patterns":["B"],"keyword_anchors":["b"],"inherits_from":"a_v001.json"}
                """.strip()
            )
            raw_a = {
                "concept_id": "a",
                "concept_name": "A",
                "family": "a",
                "heading_patterns": ["A"],
                "keyword_anchors": ["a"],
                "inherits_from": "b_v001.json",
            }
            try:
                resolve_strategy_dict(raw_a, source_path=a_path)
                raise AssertionError("Expected inheritance cycle error")
            except ValueError:
                pass

    def test_load_strategy_with_views_returns_raw_and_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            parent = root / "p_v001.json"
            parent.write_text(
                """
{"concept_id":"p","concept_name":"P","family":"p","heading_patterns":["P"],"keyword_anchors":["p"]}
                """.strip()
            )
            child = root / "c_v001.json"
            child.write_text(
                """
{"concept_id":"c","concept_name":"C","family":"p","inherits_from":"p_v001.json","heading_patterns":["C"]}
                """.strip()
            )
            strategy, raw, resolved = load_strategy_with_views(child)
            assert strategy.heading_patterns == ("C",)
            assert strategy.keyword_anchors == ("p",)
            assert raw.get("inherits_from") == "p_v001.json"
            assert resolved.get("keyword_anchors") == ["p"]


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
            raise AssertionError("Should have raised")
        except AttributeError:
            pass
