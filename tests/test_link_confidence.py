"""Tests for agent.link_confidence — 7-factor confidence scoring."""
from __future__ import annotations

from agent.link_confidence import (
    ConfidenceResult,
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_MEDIUM_THRESHOLD,
    FACTOR_WEIGHTS,
    calibrate_thresholds,
    compute_link_confidence,
    cosine_similarity,
    floats_to_bytes,
    priority_score,
)
from agent.query_filters import FilterGroup, FilterMatch


# ───────────────────── Factor weights ──────────────────────────────────


class TestFactorWeights:
    def test_weights_sum_to_one(self) -> None:
        total = sum(FACTOR_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_all_seven_factors_present(self) -> None:
        expected = {
            "article_match", "heading_exactness", "clause_signal",
            "template_consistency", "defined_term_grounding",
            "structural_prior", "semantic_similarity",
        }
        assert set(FACTOR_WEIGHTS.keys()) == expected

    def test_weight_values(self) -> None:
        assert FACTOR_WEIGHTS["article_match"] == 0.22
        assert FACTOR_WEIGHTS["heading_exactness"] == 0.28
        assert FACTOR_WEIGHTS["clause_signal"] == 0.13
        assert FACTOR_WEIGHTS["template_consistency"] == 0.10
        assert FACTOR_WEIGHTS["defined_term_grounding"] == 0.09
        assert FACTOR_WEIGHTS["structural_prior"] == 0.08
        assert FACTOR_WEIGHTS["semantic_similarity"] == 0.10


# ───────────────────── Basic scoring ──────────────────────────────────


class TestComputeLinkConfidence:
    def test_perfect_match(self) -> None:
        """All factors maximized → high confidence."""
        result = compute_link_confidence(
            heading="Indebtedness",
            article_concept="negative_covenants",
            rule_article_concepts=["negative_covenants"],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
            template_family="kirkland",
            template_stats={"kirkland": 0.95},
            clause_signals={"debt_phrase": 0.9, "incur_phrase": 0.85},
            defined_terms_present=["Permitted Indebtedness", "Debt"],
            expected_defined_terms=["Permitted Indebtedness", "Debt"],
            structural_prior={"primary_location": "Negative covenants", "prior_probability": 0.9},
        )
        assert isinstance(result, ConfidenceResult)
        assert result.score >= 0.8
        assert result.tier == "high"
        assert len(result.breakdown) == 7

    def test_poor_match(self) -> None:
        """Most factors zero → low confidence."""
        result = compute_link_confidence(
            heading="Unrelated Section",
            article_concept="definitions",
            rule_article_concepts=["negative_covenants"],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
        )
        assert result.score < 0.5
        assert result.tier == "low"

    def test_partial_match(self) -> None:
        """Some factors match → medium confidence."""
        result = compute_link_confidence(
            heading="Limitation on Indebtedness",
            article_concept="negative_covenants",
            rule_article_concepts=["negative_covenants"],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
        )
        # article_match = 1.0 (0.22), heading = 0.7 substring (0.28*0.7),
        # others neutral at 0.5
        assert 0.4 <= result.score <= 0.9

    def test_score_clamped_to_0_1(self) -> None:
        result = compute_link_confidence(
            heading="X",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
        )
        assert 0.0 <= result.score <= 1.0

    def test_breakdown_has_all_factors(self) -> None:
        result = compute_link_confidence(
            heading="Test",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="Test"),
        )
        assert set(result.breakdown.keys()) == set(FACTOR_WEIGHTS.keys())

    def test_why_matched_has_all_factors(self) -> None:
        result = compute_link_confidence(
            heading="Test",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="Test"),
        )
        assert set(result.why_matched.keys()) == set(FACTOR_WEIGHTS.keys())


# ───────────────────── Individual factors ─────────────────────────────


class TestArticleMatch:
    def test_exact_match(self) -> None:
        result = compute_link_confidence(
            heading="X",
            article_concept="negative_covenants",
            rule_article_concepts=["negative_covenants"],
            rule_heading_ast=FilterMatch(value="X"),
        )
        assert result.breakdown["article_match"] == 1.0

    def test_mismatch(self) -> None:
        result = compute_link_confidence(
            heading="X",
            article_concept="definitions",
            rule_article_concepts=["negative_covenants"],
            rule_heading_ast=FilterMatch(value="X"),
        )
        assert result.breakdown["article_match"] == 0.0

    def test_no_constraint_neutral(self) -> None:
        result = compute_link_confidence(
            heading="X",
            article_concept="anything",
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
        )
        assert result.breakdown["article_match"] == 0.5


class TestHeadingExactness:
    def test_exact_match(self) -> None:
        result = compute_link_confidence(
            heading="Indebtedness",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
        )
        assert result.breakdown["heading_exactness"] == 1.0

    def test_pattern_is_substring(self) -> None:
        """Pattern "Indebtedness" is a substring of heading "Limitation on Indebtedness"."""
        result = compute_link_confidence(
            heading="Limitation on Indebtedness",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
        )
        assert result.breakdown["heading_exactness"] == 0.7

    def test_heading_is_substring(self) -> None:
        """Heading "Liens" is a substring of pattern "Liens and Pledges"."""
        result = compute_link_confidence(
            heading="Liens",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="Liens and Pledges"),
        )
        assert result.breakdown["heading_exactness"] == 0.5

    def test_or_group_best_match(self) -> None:
        """Best match among OR options."""
        result = compute_link_confidence(
            heading="Indebtedness",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterGroup(
                operator="or",
                children=(
                    FilterMatch(value="Indebtedness"),
                    FilterMatch(value="Debt"),
                ),
            ),
        )
        assert result.breakdown["heading_exactness"] == 1.0

    def test_no_match(self) -> None:
        result = compute_link_confidence(
            heading="Completely Different",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
        )
        assert result.breakdown["heading_exactness"] == 0.0

    def test_empty_heading(self) -> None:
        result = compute_link_confidence(
            heading="",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
        )
        assert result.breakdown["heading_exactness"] == 0.0

    def test_case_insensitive(self) -> None:
        result = compute_link_confidence(
            heading="INDEBTEDNESS",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="indebtedness"),
        )
        assert result.breakdown["heading_exactness"] == 1.0


class TestClauseSignal:
    def test_no_signals_neutral(self) -> None:
        result = compute_link_confidence(
            heading="X",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
        )
        assert result.breakdown["clause_signal"] == 0.5  # not checked

    def test_high_signals(self) -> None:
        result = compute_link_confidence(
            heading="X",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
            clause_signals={"phrase_a": 0.9, "phrase_b": 0.8},
        )
        assert result.breakdown["clause_signal"] > 0.5

    def test_empty_signals(self) -> None:
        result = compute_link_confidence(
            heading="X",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
            clause_signals={},
        )
        assert result.breakdown["clause_signal"] == 0.3


class TestSemanticSimilarity:
    def test_unavailable_returns_neutral(self) -> None:
        result = compute_link_confidence(
            heading="X",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
        )
        assert result.breakdown["semantic_similarity"] == 0.5
        assert result.why_matched["semantic_similarity"]["reason"] == "embeddings_unavailable"

    def test_with_embeddings(self) -> None:
        # Create similar vectors
        vec_a = floats_to_bytes([1.0, 0.0, 0.0])
        vec_b = floats_to_bytes([0.9, 0.1, 0.0])
        result = compute_link_confidence(
            heading="X",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
            section_embedding=vec_a,
            family_centroid=vec_b,
        )
        assert result.breakdown["semantic_similarity"] > 0.5

    def test_orthogonal_embeddings(self) -> None:
        vec_a = floats_to_bytes([1.0, 0.0, 0.0])
        vec_b = floats_to_bytes([0.0, 1.0, 0.0])
        result = compute_link_confidence(
            heading="X",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
            section_embedding=vec_a,
            family_centroid=vec_b,
        )
        # Cosine similarity = 0, mapped to 0.5
        assert abs(result.breakdown["semantic_similarity"] - 0.5) < 0.01

    def test_malformed_embeddings_fallback_to_neutral(self) -> None:
        # Mismatched dimensions force cosine_similarity to raise ValueError.
        section_vec = floats_to_bytes([1.0])
        centroid_vec = floats_to_bytes([1.0, 0.0])
        result = compute_link_confidence(
            heading="X",
            article_concept=None,
            rule_article_concepts=[],
            rule_heading_ast=FilterMatch(value="X"),
            section_embedding=section_vec,
            family_centroid=centroid_vec,
        )
        assert result.breakdown["semantic_similarity"] == 0.5
        assert result.why_matched["semantic_similarity"]["reason"] == "embedding_decode_error"


# ───────────────────── Tier thresholds ────────────────────────────────


class TestTiers:
    def test_high_tier(self) -> None:
        # Construct a result that should be high
        result = compute_link_confidence(
            heading="Indebtedness",
            article_concept="negative_covenants",
            rule_article_concepts=["negative_covenants"],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
            template_family="kirkland",
            template_stats={"kirkland": 0.95},
            clause_signals={"phrase": 0.9},
            defined_terms_present=["Debt"],
            expected_defined_terms=["Debt"],
            structural_prior={"primary_location": "negative_covenants", "prior_probability": 0.9},
            section_embedding=floats_to_bytes([1.0, 0.0]),
            family_centroid=floats_to_bytes([0.95, 0.05]),
        )
        assert result.tier == "high"

    def test_custom_calibration_thresholds(self) -> None:
        result = compute_link_confidence(
            heading="Indebtedness",
            article_concept="negative_covenants",
            rule_article_concepts=["negative_covenants"],
            rule_heading_ast=FilterMatch(value="Indebtedness"),
            calibration={"high_threshold": 0.95, "medium_threshold": 0.6},
        )
        # With higher threshold, might not be "high" anymore
        if result.score < 0.95:
            assert result.tier != "high"


# ───────────────────── Cosine similarity ──────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = floats_to_bytes([1.0, 2.0, 3.0])
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_opposite_vectors(self) -> None:
        a = floats_to_bytes([1.0, 0.0])
        b = floats_to_bytes([-1.0, 0.0])
        assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        a = floats_to_bytes([1.0, 0.0])
        b = floats_to_bytes([0.0, 1.0])
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_dimension_mismatch_raises(self) -> None:
        a = floats_to_bytes([1.0, 2.0])
        b = floats_to_bytes([1.0, 2.0, 3.0])
        try:
            cosine_similarity(a, b)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_empty_raises(self) -> None:
        try:
            cosine_similarity(b"", b"")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


# ───────────────────── Priority score ─────────────────────────────────


class TestPriorityScore:
    def test_uncertain_high_priority(self) -> None:
        """Confidence 0.5 = maximum uncertainty → high priority."""
        ps, us, _, _ = priority_score(0.5)
        assert us == 1.0  # max uncertainty
        assert ps > 0.4

    def test_confident_low_priority(self) -> None:
        """Confidence 1.0 = no uncertainty → low priority."""
        _, us, _, _ = priority_score(1.0)
        assert us == 0.0

    def test_facility_size_impact(self) -> None:
        """Larger facility = higher impact score."""
        _, _, imp_small, _ = priority_score(0.5, facility_size_mm=100.0)
        _, _, imp_large, _ = priority_score(0.5, facility_size_mm=4000.0)
        assert imp_large > imp_small

    def test_drift_factor(self) -> None:
        """Higher drift = higher drift score."""
        ps_no_drift, _, _, ds_no = priority_score(0.5, drift_delta=0.0)
        ps_drift, _, _, ds_yes = priority_score(0.5, drift_delta=0.3)
        assert ds_yes > ds_no
        assert ps_drift > ps_no_drift


# ───────────────────── Calibration ────────────────────────────────────


class TestCalibration:
    def test_empty_adjudicated(self) -> None:
        result = calibrate_thresholds([])
        assert result["high_threshold"] == DEFAULT_HIGH_THRESHOLD
        assert result["sample_size"] == 0

    def test_all_positive(self) -> None:
        items = [
            {"confidence": 0.9, "label": "positive"},
            {"confidence": 0.8, "label": "positive"},
            {"confidence": 0.7, "label": "positive"},
        ]
        result = calibrate_thresholds(items)
        assert result["precision"] > 0.0
        assert result["recall"] > 0.0
        assert result["sample_size"] == 3

    def test_precision_target(self) -> None:
        """With mixed labels, calibration should target precision."""
        items = [
            {"confidence": 0.95, "label": "positive"},
            {"confidence": 0.90, "label": "positive"},
            {"confidence": 0.85, "label": "positive"},
            {"confidence": 0.80, "label": "positive"},
            {"confidence": 0.75, "label": "negative"},
            {"confidence": 0.70, "label": "positive"},
            {"confidence": 0.60, "label": "negative"},
            {"confidence": 0.50, "label": "negative"},
            {"confidence": 0.40, "label": "negative"},
            {"confidence": 0.30, "label": "negative"},
        ]
        result = calibrate_thresholds(items, target_precision=0.9)
        # At threshold 0.80, we have 4 positives, 0 negatives → precision 1.0
        assert result["precision"] >= 0.9

    def test_expected_review_load(self) -> None:
        items = [
            {"confidence": 0.9, "label": "positive"},
            {"confidence": 0.7, "label": "positive"},
            {"confidence": 0.5, "label": "negative"},
            {"confidence": 0.3, "label": "negative"},
        ]
        result = calibrate_thresholds(items)
        assert "expected_review_load" in result
        assert isinstance(result["expected_review_load"], int)

    def test_no_positives(self) -> None:
        items = [
            {"confidence": 0.9, "label": "negative"},
            {"confidence": 0.5, "label": "negative"},
        ]
        result = calibrate_thresholds(items)
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0
