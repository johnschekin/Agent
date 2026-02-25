"""Tests for agent.conflict_matrix — ontology-aware conflict policy matrix."""
from __future__ import annotations

from agent.conflict_matrix import (
    ALL_POLICIES,
    ConflictPolicy,
    EDGE_TO_POLICY,
    POLICY_PRIORITY,
    build_conflict_matrix,
    check_section_conflicts,
    get_conflicting_families,
    lookup_policy,
    matrix_to_dict,
    policy_to_row,
    row_to_policy,
)


# ───────────────────── Constants ──────────────────────────────────────


class TestConstants:
    def test_all_18_edge_types_mapped(self) -> None:
        assert len(EDGE_TO_POLICY) == 18

    def test_all_6_policies_have_priority(self) -> None:
        assert len(POLICY_PRIORITY) == 6
        expected = {"exclusive", "warn", "compound_covenant", "shared_ok", "expected_overlap", "independent"}
        assert set(POLICY_PRIORITY.keys()) == expected

    def test_priority_ordering(self) -> None:
        """Higher number = higher priority."""
        assert POLICY_PRIORITY["exclusive"] > POLICY_PRIORITY["warn"]
        assert POLICY_PRIORITY["warn"] > POLICY_PRIORITY["compound_covenant"]
        assert POLICY_PRIORITY["compound_covenant"] > POLICY_PRIORITY["shared_ok"]
        assert POLICY_PRIORITY["shared_ok"] > POLICY_PRIORITY["expected_overlap"]
        assert POLICY_PRIORITY["expected_overlap"] > POLICY_PRIORITY["independent"]

    def test_exclusive_edges(self) -> None:
        exclusive_edges = [k for k, v in EDGE_TO_POLICY.items() if v == "exclusive"]
        assert "EXCLUDES_FROM" in exclusive_edges
        assert "PREVENTS" in exclusive_edges
        assert "BLOCKED_BY" in exclusive_edges

    def test_warn_edges(self) -> None:
        warn_edges = [k for k, v in EDGE_TO_POLICY.items() if v == "warn"]
        assert "CONSTRAINS" in warn_edges
        assert "RECLASSIFIES_TO" in warn_edges

    def test_shared_ok_edges(self) -> None:
        shared = [k for k, v in EDGE_TO_POLICY.items() if v == "shared_ok"]
        assert "COMPLEMENTS" in shared
        assert "CROSS_REFERENCES" in shared

    def test_all_policies_frozen(self) -> None:
        assert isinstance(ALL_POLICIES, frozenset)
        assert len(ALL_POLICIES) == 6


# ───────────────────── build_conflict_matrix ──────────────────────────


def _make_edge(source: str, target: str, edge_type: str) -> dict:
    return {
        "source": source,
        "target": target,
        "edge_type": edge_type,
        "source_family": source,
        "target_family": target,
    }


class TestBuildConflictMatrix:
    def test_basic_exclusive(self) -> None:
        edges = [_make_edge("family_a", "family_b", "EXCLUDES_FROM")]
        result = build_conflict_matrix(edges, {}, ontology_version="test")
        assert len(result) == 1
        assert result[0].policy == "exclusive"
        assert result[0].family_a == "family_a"
        assert result[0].family_b == "family_b"

    def test_symmetric_storage(self) -> None:
        """(A, B) always stored with A < B lexicographically."""
        edges = [_make_edge("zebra", "alpha", "EXCLUDES_FROM")]
        result = build_conflict_matrix(edges, {})
        assert result[0].family_a == "alpha"
        assert result[0].family_b == "zebra"

    def test_priority_resolution(self) -> None:
        """When multiple edges exist for a pair, highest-priority policy wins."""
        edges = [
            _make_edge("a", "b", "COMPLEMENTS"),     # shared_ok (2)
            _make_edge("a", "b", "EXCLUDES_FROM"),    # exclusive (5)
        ]
        result = build_conflict_matrix(edges, {})
        assert len(result) == 1
        assert result[0].policy == "exclusive"

    def test_multiple_pairs(self) -> None:
        edges = [
            _make_edge("debt", "liens", "EXCLUDES_FROM"),
            _make_edge("rp", "inv", "COMPLEMENTS"),
        ]
        result = build_conflict_matrix(edges, {})
        assert len(result) == 2
        families = {(p.family_a, p.family_b) for p in result}
        assert ("debt", "liens") in families
        assert ("inv", "rp") in families

    def test_independent_excluded(self) -> None:
        """Pure 'independent' relationships not included in results."""
        edges = [_make_edge("a", "b", "DEPENDS_ON")]
        result = build_conflict_matrix(edges, {})
        assert len(result) == 0

    def test_same_family_edge_skipped(self) -> None:
        """Intra-family edges don't create conflicts."""
        edges = [_make_edge("family_a", "family_a", "EXCLUDES_FROM")]
        result = build_conflict_matrix(edges, {})
        assert len(result) == 0

    def test_unknown_edge_type_skipped(self) -> None:
        edges = [_make_edge("a", "b", "UNKNOWN_EDGE")]
        result = build_conflict_matrix(edges, {})
        assert len(result) == 0

    def test_edge_types_collected(self) -> None:
        edges = [
            _make_edge("a", "b", "CONSTRAINS"),
            _make_edge("a", "b", "MODIFIES"),
        ]
        result = build_conflict_matrix(edges, {})
        assert len(result) == 1
        assert "CONSTRAINS" in result[0].edge_types
        assert "MODIFIES" in result[0].edge_types

    def test_reason_string_not_empty(self) -> None:
        edges = [_make_edge("a", "b", "EXCLUDES_FROM")]
        result = build_conflict_matrix(edges, {})
        assert result[0].reason != ""
        assert "exclusive" in result[0].reason.lower() or "a" in result[0].reason

    def test_ontology_version_tracked(self) -> None:
        edges = [_make_edge("a", "b", "EXCLUDES_FROM")]
        result = build_conflict_matrix(edges, {}, ontology_version="v2.5.1")
        assert result[0].ontology_version == "v2.5.1"

    def test_node_lookup_fallback(self) -> None:
        """When source_family not in edge, falls back to node lookup."""
        edges = [{"source": "concept_x", "target": "concept_y", "edge_type": "EXCLUDES_FROM"}]
        nodes = {
            "concept_x": {"family_id": "family_x"},
            "concept_y": {"family_id": "family_y"},
        }
        result = build_conflict_matrix(edges, nodes)
        assert len(result) == 1
        assert result[0].family_a == "family_x"
        assert result[0].family_b == "family_y"

    def test_node_lookup_fallback_to_concept_id_when_family_missing(self) -> None:
        edges = [{"source": "concept_x", "target": "concept_y", "edge_type": "CONSTRAINS"}]
        nodes = {
            "concept_x": {"label": "Concept X"},
            "concept_y": {"label": "Concept Y"},
        }
        result = build_conflict_matrix(edges, nodes)
        assert len(result) == 1
        assert result[0].family_a == "concept_x"
        assert result[0].family_b == "concept_y"


# ───────────────────── Lookup helpers ─────────────────────────────────


class TestLookup:
    def _build_matrix(self) -> dict:
        edges = [
            _make_edge("debt", "liens", "EXCLUDES_FROM"),
            _make_edge("rp", "inv", "COMPLEMENTS"),
            _make_edge("debt", "rp", "CONSTRAINS"),
        ]
        policies = build_conflict_matrix(edges, {})
        return matrix_to_dict(policies)

    def test_lookup_existing(self) -> None:
        m = self._build_matrix()
        assert lookup_policy(m, "debt", "liens") == "exclusive"

    def test_lookup_reversed_order(self) -> None:
        """Order shouldn't matter — canonical pair is used."""
        m = self._build_matrix()
        assert lookup_policy(m, "liens", "debt") == "exclusive"

    def test_lookup_missing_returns_independent(self) -> None:
        m = self._build_matrix()
        assert lookup_policy(m, "unknown_a", "unknown_b") == "independent"

    def test_get_conflicting_families(self) -> None:
        m = self._build_matrix()
        conflicts = get_conflicting_families(m, "debt", min_policy="warn")
        # debt-liens (exclusive) and debt-rp (warn)
        assert len(conflicts) == 2
        # Sorted by priority: exclusive first
        assert conflicts[0].policy == "exclusive"

    def test_get_conflicting_families_min_exclusive(self) -> None:
        m = self._build_matrix()
        conflicts = get_conflicting_families(m, "debt", min_policy="exclusive")
        assert len(conflicts) == 1
        assert conflicts[0].policy == "exclusive"


# ───────────────────── Section conflict check ─────────────────────────


class TestSectionConflicts:
    def test_no_conflicts(self) -> None:
        m = matrix_to_dict([])
        conflicts = check_section_conflicts(m, ["a", "b", "c"])
        assert conflicts == []

    def test_detects_conflict(self) -> None:
        edges = [_make_edge("a", "b", "EXCLUDES_FROM")]
        m = matrix_to_dict(build_conflict_matrix(edges, {}))
        conflicts = check_section_conflicts(m, ["a", "b"])
        assert len(conflicts) == 1
        assert conflicts[0].policy == "exclusive"

    def test_multiple_conflicts_sorted(self) -> None:
        edges = [
            _make_edge("a", "b", "EXCLUDES_FROM"),   # exclusive
            _make_edge("a", "c", "COMPLEMENTS"),       # shared_ok
        ]
        m = matrix_to_dict(build_conflict_matrix(edges, {}))
        conflicts = check_section_conflicts(m, ["a", "b", "c"])
        assert len(conflicts) == 2
        # Exclusive should be first (higher priority)
        assert conflicts[0].policy == "exclusive"
        assert conflicts[1].policy == "shared_ok"

    def test_single_family_no_conflicts(self) -> None:
        edges = [_make_edge("a", "b", "EXCLUDES_FROM")]
        m = matrix_to_dict(build_conflict_matrix(edges, {}))
        conflicts = check_section_conflicts(m, ["a"])
        assert conflicts == []


# ───────────────────── Compound covenants ─────────────────────────────


class TestCompoundCovenants:
    def test_compound_covenant_policy_exists(self) -> None:
        """compound_covenant is a valid policy."""
        assert "compound_covenant" in POLICY_PRIORITY
        assert POLICY_PRIORITY["compound_covenant"] == 3

    def test_compound_between_warn_and_shared(self) -> None:
        """compound_covenant priority is between warn and shared_ok."""
        assert POLICY_PRIORITY["warn"] > POLICY_PRIORITY["compound_covenant"]
        assert POLICY_PRIORITY["compound_covenant"] > POLICY_PRIORITY["shared_ok"]

    def test_meta_rule_override(self) -> None:
        """User can override computed policy with meta-rule."""
        edges = [_make_edge("rp", "inv", "EXCLUDES_FROM")]
        policies = build_conflict_matrix(edges, {})
        m = matrix_to_dict(policies)
        # Original: exclusive
        assert lookup_policy(m, "inv", "rp") == "exclusive"

        # Override to compound_covenant
        overridden = ConflictPolicy(
            family_a="inv",
            family_b="rp",
            policy="compound_covenant",
            reason="User override: combined RP/Investments section is valid",
            edge_types=("EXCLUDES_FROM",),
            ontology_version="test",
        )
        m[(overridden.family_a, overridden.family_b)] = overridden
        assert lookup_policy(m, "inv", "rp") == "compound_covenant"


# ───────────────────── Serialization ──────────────────────────────────


class TestSerialization:
    def test_round_trip(self) -> None:
        policy = ConflictPolicy(
            family_a="debt",
            family_b="liens",
            policy="exclusive",
            reason="test reason",
            edge_types=("EXCLUDES_FROM", "PREVENTS"),
            ontology_version="v2.5.1",
        )
        row = policy_to_row(policy)
        restored = row_to_policy(row)
        assert restored.family_a == policy.family_a
        assert restored.family_b == policy.family_b
        assert restored.policy == policy.policy
        assert restored.reason == policy.reason
        assert set(restored.edge_types) == set(policy.edge_types)
        assert restored.ontology_version == policy.ontology_version

    def test_row_has_expected_keys(self) -> None:
        policy = ConflictPolicy(
            family_a="a", family_b="b", policy="warn",
            reason="test", edge_types=("CONSTRAINS",), ontology_version="v1",
        )
        row = policy_to_row(policy)
        assert "family_a" in row
        assert "family_b" in row
        assert "policy" in row
        assert "reason" in row
        assert "edge_types" in row
        assert "ontology_version" in row

    def test_frozen_dataclass(self) -> None:
        policy = ConflictPolicy(
            family_a="a", family_b="b", policy="warn",
            reason="test", edge_types=(), ontology_version="v1",
        )
        try:
            policy.policy = "exclusive"  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass
