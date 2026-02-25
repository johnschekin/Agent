"""Unit tests for src/agent/discovery.py — all 6 analysis primitive groups.

Uses synthetic data only (no DuckDB, no filesystem).
"""
from __future__ import annotations

import pytest

from agent.discovery import (
    ClusterResult,
    CooccurrenceMatrix,
    active_families,
    cluster_family_sections,
    compute_cooccurrence,
    compute_correlations,
    compute_template_conditioned_profiles,
    compute_template_conditioned_profiles_with_headings,
    extract_adjacency_patterns,
    extract_adjacency_patterns_with_headings,
    parse_family_notes,
    score_anomalies,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic data
# ---------------------------------------------------------------------------

def _make_family_sections() -> dict[str, list[tuple[str, str, int]]]:
    """Two families, each present in some docs."""
    return {
        "indebtedness": [
            ("doc1", "7.01", 7),
            ("doc1", "7.02", 7),
            ("doc2", "7.01", 7),
            ("doc3", "6.01", 6),
        ],
        "liens": [
            ("doc1", "7.03", 7),
            ("doc2", "7.02", 7),
            ("doc4", "7.01", 7),
        ],
    }


def _make_all_sections_ordered() -> dict[str, list[tuple[str, str, int, int]]]:
    """All sections with positions, ordered by char_start."""
    return {
        "doc1": [
            ("doc1", "7.01", 7, 0),
            ("doc1", "7.02", 7, 1),
            ("doc1", "7.03", 7, 2),
            ("doc1", "7.04", 7, 3),
        ],
        "doc2": [
            ("doc2", "7.01", 7, 0),
            ("doc2", "7.02", 7, 1),
            ("doc2", "7.03", 7, 2),
        ],
        "doc3": [
            ("doc3", "6.01", 6, 0),
            ("doc3", "6.02", 6, 1),
        ],
        "doc4": [
            ("doc4", "7.01", 7, 0),
            ("doc4", "7.02", 7, 1),
        ],
    }


# ---------------------------------------------------------------------------
# E1.1 — Co-occurrence Matrix
# ---------------------------------------------------------------------------

class TestCooccurrence:
    def test_symmetric_and_diagonal(self) -> None:
        fam_secs = _make_family_sections()
        all_secs = _make_all_sections_ordered()
        result = compute_cooccurrence(fam_secs, all_secs)

        assert isinstance(result, CooccurrenceMatrix)
        assert len(result.families) == 2
        n = len(result.families)

        # Doc-level: symmetric
        for i in range(n):
            for j in range(n):
                assert result.doc_matrix[i][j] == result.doc_matrix[j][i]

        # Article-level: symmetric
        for i in range(n):
            for j in range(n):
                assert result.article_matrix[i][j] == result.article_matrix[j][i]

        # Adjacency: symmetric
        for i in range(n):
            for j in range(n):
                assert result.adjacency_matrix[i][j] == result.adjacency_matrix[j][i]

    def test_doc_level_counts(self) -> None:
        fam_secs = _make_family_sections()
        all_secs = _make_all_sections_ordered()
        result = compute_cooccurrence(fam_secs, all_secs)

        idx = {f: i for i, f in enumerate(result.families)}
        # indebtedness in doc1, doc2, doc3; liens in doc1, doc2, doc4
        # shared docs: doc1, doc2
        assert result.doc_matrix[idx["indebtedness"]][idx["liens"]] == 2

    def test_article_level_counts(self) -> None:
        fam_secs = _make_family_sections()
        all_secs = _make_all_sections_ordered()
        result = compute_cooccurrence(fam_secs, all_secs)

        idx = {f: i for i, f in enumerate(result.families)}
        # Both in article 7 of doc1 and doc2
        assert result.article_matrix[idx["indebtedness"]][idx["liens"]] == 2

    def test_adjacency_counts(self) -> None:
        fam_secs = _make_family_sections()
        all_secs = _make_all_sections_ordered()
        result = compute_cooccurrence(fam_secs, all_secs)

        idx = {f: i for i, f in enumerate(result.families)}
        # In doc1: indebtedness at pos 0,1; liens at pos 2.
        #   pos 1 and pos 2 are ±1 → adjacency hit
        # In doc2: indebtedness at pos 0; liens at pos 1.
        #   pos 0 and pos 1 are ±1 → adjacency hit
        assert result.adjacency_matrix[idx["indebtedness"]][idx["liens"]] >= 2

    def test_empty_input(self) -> None:
        result = compute_cooccurrence({}, {})
        assert result.families == ()
        assert result.doc_matrix == ()


# ---------------------------------------------------------------------------
# E1.2 — Correlation
# ---------------------------------------------------------------------------

class TestCorrelation:
    def test_perfect_positive(self) -> None:
        features = {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0],
            "y": [2.0, 4.0, 6.0, 8.0, 10.0],
        }
        results = compute_correlations(features)
        assert len(results) == 1
        assert results[0].pearson_r == pytest.approx(1.0, abs=0.01)
        assert results[0].spearman_rho == pytest.approx(1.0, abs=0.01)
        assert results[0].n == 5

    def test_perfect_negative(self) -> None:
        features = {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0],
            "y": [10.0, 8.0, 6.0, 4.0, 2.0],
        }
        results = compute_correlations(features)
        assert results[0].pearson_r == pytest.approx(-1.0, abs=0.01)

    def test_none_filtering(self) -> None:
        features: dict[str, list[float | None]] = {
            "x": [1.0, None, 3.0, None, 5.0],
            "y": [2.0, 4.0, 6.0, 8.0, 10.0],
        }
        results = compute_correlations(features)
        assert len(results) == 1
        assert results[0].n == 3  # only positions 0, 2, 4

    def test_insufficient_data(self) -> None:
        features: dict[str, list[float | None]] = {
            "x": [1.0, None],
            "y": [None, 2.0],
        }
        results = compute_correlations(features)
        assert len(results) == 0

    def test_specific_pairs(self) -> None:
        features = {
            "a": [1.0, 2.0, 3.0],
            "b": [4.0, 5.0, 6.0],
            "c": [7.0, 8.0, 9.0],
        }
        results = compute_correlations(features, pairs=[("a", "c")])
        assert len(results) == 1
        assert results[0].feature_a == "a"
        assert results[0].feature_b == "c"


# ---------------------------------------------------------------------------
# E1.3 — Adjacency Patterns
# ---------------------------------------------------------------------------

class TestAdjacencyPatterns:
    def test_basic_extraction(self) -> None:
        fam_secs = _make_family_sections()
        all_secs = _make_all_sections_ordered()
        result = extract_adjacency_patterns(
            fam_secs, all_secs, window=2, min_frequency=1,
        )

        assert "indebtedness" in result
        assert "liens" in result
        # indebtedness has sections in docs 1,2,3
        assert len(result["indebtedness"]) > 0

    def test_min_frequency_filter(self) -> None:
        fam_secs = _make_family_sections()
        all_secs = _make_all_sections_ordered()
        # High min_frequency should filter most patterns
        result = extract_adjacency_patterns(
            fam_secs, all_secs, window=1, min_frequency=100,
        )
        for patterns in result.values():
            assert len(patterns) == 0

    def test_with_headings(self) -> None:
        fam_secs: dict[str, list[tuple[str, str, int]]] = {
            "indebtedness": [("doc1", "7.01", 7)],
        }
        all_secs_h: dict[str, list[tuple[str, str, str, int, int]]] = {
            "doc1": [
                ("doc1", "7.01", "Indebtedness", 7, 0),
                ("doc1", "7.02", "Liens", 7, 1),
                ("doc1", "7.03", "Investments", 7, 2),
            ],
        }
        result = extract_adjacency_patterns_with_headings(
            fam_secs, all_secs_h, window=2, min_frequency=1,
        )
        assert "indebtedness" in result
        neighbors = {p.neighbor_heading for p in result["indebtedness"]}
        assert "liens" in neighbors


# ---------------------------------------------------------------------------
# E1.4 — Anomaly Scoring
# ---------------------------------------------------------------------------

class TestAnomalyScoring:
    def test_detects_outlier(self) -> None:
        # 9 normal sections + 1 extreme outlier
        normal = [{"word_count": 1000.0, "clause_depth": 3.0}] * 9
        outlier = [{"word_count": 50000.0, "clause_depth": 30.0}]
        features = normal + outlier
        ids = [(f"doc{i}", f"s{i}") for i in range(10)]

        results = score_anomalies(features, ids, threshold_z=2.0)
        assert len(results) >= 1
        assert results[0].doc_id == "doc9"
        assert results[0].z_score > 2.0

    def test_no_outliers_in_uniform(self) -> None:
        features = [{"x": 5.0, "y": 10.0}] * 10
        ids = [(f"d{i}", f"s{i}") for i in range(10)]
        results = score_anomalies(features, ids, threshold_z=2.5)
        assert len(results) == 0

    def test_insufficient_data(self) -> None:
        features = [{"x": 1.0}]
        ids = [("d0", "s0")]
        results = score_anomalies(features, ids)
        assert results == []


# ---------------------------------------------------------------------------
# E1.5 — Template-Conditioned Profiling
# ---------------------------------------------------------------------------

class TestTemplateConditioned:
    def test_basic_profiling(self) -> None:
        fam_secs = {
            "indebtedness": [
                ("doc1", "7.01", 7, "cahill"),
                ("doc2", "6.01", 6, "simpson"),
                ("doc3", "7.01", 7, "cahill"),
            ],
        }
        sec_features: dict[tuple[str, str], dict[str, float]] = {
            ("doc1", "7.01"): {"word_count": 1200.0},
            ("doc2", "6.01"): {"word_count": 800.0},
            ("doc3", "7.01"): {"word_count": 1400.0},
        }
        result = compute_template_conditioned_profiles(fam_secs, sec_features)

        assert "indebtedness" in result
        profiles = result["indebtedness"]
        assert len(profiles) == 2  # cahill and simpson

        # Cahill should be first (more sections)
        assert profiles[0].template_family == "cahill"
        assert profiles[0].section_count == 2
        assert profiles[0].avg_article_num == 7.0

    def test_with_headings(self) -> None:
        fam_secs: dict[str, list[tuple[str, str, int, str, str]]] = {
            "liens": [
                ("doc1", "7.03", 7, "cahill", "Liens"),
                ("doc2", "7.02", 7, "cahill", "Limitation on Liens"),
            ],
        }
        sec_features: dict[tuple[str, str], dict[str, float]] = {
            ("doc1", "7.03"): {"word_count": 900.0},
            ("doc2", "7.02"): {"word_count": 1100.0},
        }
        result = compute_template_conditioned_profiles_with_headings(
            fam_secs, sec_features,
        )
        assert "liens" in result
        assert result["liens"][0].template_family == "cahill"
        # Heading distribution should have normalized headings
        dist = result["liens"][0].heading_distribution
        assert "liens" in dist or "limitation on liens" in dist


# ---------------------------------------------------------------------------
# E1.6 — Section Clustering
# ---------------------------------------------------------------------------

class TestClustering:
    def test_basic_clustering(self) -> None:
        # Two clear clusters: high word_count vs low
        feature_matrix = (
            [{"word_count": 100.0 + i, "depth": 2.0} for i in range(20)]
            + [{"word_count": 10000.0 + i, "depth": 8.0} for i in range(20)]
        )
        result = cluster_family_sections(feature_matrix, max_clusters=4)
        if result is None:
            pytest.skip("sklearn not available")

        assert isinstance(result, ClusterResult)
        assert result.n_clusters >= 2
        assert result.silhouette_score > 0.0
        assert len(result.labels) == 40
        assert len(result.pca_explained_variance) > 0
        assert len(result.feature_names) == 2

    def test_insufficient_data(self) -> None:
        feature_matrix = [{"x": 1.0}] * 3
        result = cluster_family_sections(feature_matrix)
        assert result is None

    def test_cluster_summaries(self) -> None:
        feature_matrix = (
            [{"a": 1.0, "b": 10.0}] * 15
            + [{"a": 100.0, "b": 1000.0}] * 15
        )
        result = cluster_family_sections(feature_matrix, max_clusters=3)
        if result is None:
            pytest.skip("sklearn not available")

        assert len(result.cluster_summaries) == result.n_clusters
        for summary in result.cluster_summaries:
            assert "size" in summary


# ---------------------------------------------------------------------------
# Family Notes Parsing
# ---------------------------------------------------------------------------

class TestFamilyNotes:
    def test_parse_basic(self) -> None:
        raw = {
            "_meta": {"description": "test"},
            "debt_capacity.indebtedness": {
                "status": "active",
                "location_guidance": "Negative covenants article",
                "primary_location": "Negative covenants article",
                "co_examine": ["indebtedness section"],
                "notes": "Always a section",
            },
            "cash_flow": {
                "status": "defer_discussion",
                "notes": "Deferred",
            },
        }
        result = parse_family_notes(raw)
        assert len(result) == 2
        assert result["debt_capacity.indebtedness"].status == "active"
        assert result["cash_flow"].status == "defer_discussion"

    def test_active_filter(self) -> None:
        raw = {
            "fam_a": {"status": "active", "notes": ""},
            "fam_b": {"status": "defer_discussion", "notes": ""},
            "fam_c": {"status": "removed", "notes": ""},
        }
        notes = parse_family_notes(raw)
        actives = active_families(notes)
        assert len(actives) == 1
        assert "fam_a" in actives

    def test_structural_variants(self) -> None:
        raw = {
            "cash_flow.rp": {
                "status": "active",
                "structural_variants": ["Bond-style", "Regular", "Hybrid A"],
                "notes": "Important",
            },
        }
        notes = parse_family_notes(raw)
        assert len(notes["cash_flow.rp"].structural_variants) == 3
