"""7-factor confidence scoring for family link quality assessment.

Computes a composite confidence score (0.0–1.0) for a proposed section-to-family
link based on seven weighted factors:

1. **article_match** (0.22) — article concept in rule concepts
2. **heading_exactness** (0.28) — heading match quality (exact/substring)
3. **clause_signal** (0.13) — DNA phrase density in clause text
4. **template_consistency** (0.10) — historical rate for template family
5. **defined_term_grounding** (0.09) — presence of key defined terms
6. **structural_prior** (0.08) — family location guidance from ontology
7. **semantic_similarity** (0.10) — cosine similarity of section embedding to family centroid

Tier thresholds (calibratable per family):
- **High** >= 0.8 → ``status = "active"`` (auto-linked)
- **Medium** 0.5–0.8 → ``status = "pending_review"`` (queued for review)
- **Low** < 0.5 → not linked (suppressed)
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any

from agent.query_filters import FilterExpression, FilterMatch

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    """Result of confidence scoring for a candidate link."""

    score: float                          # 0.0 – 1.0
    tier: str                             # "high" | "medium" | "low"
    breakdown: dict[str, float]           # per-factor scores
    why_matched: dict[str, dict[str, Any]]  # factor-level evidence


# ---------------------------------------------------------------------------
# Factor weights
# ---------------------------------------------------------------------------

FACTOR_WEIGHTS: dict[str, float] = {
    "article_match": 0.22,
    "heading_exactness": 0.28,
    "clause_signal": 0.13,
    "template_consistency": 0.10,
    "defined_term_grounding": 0.09,
    "structural_prior": 0.08,
    "semantic_similarity": 0.10,
}

# Verify weights sum to 1.0
_TOTAL_WEIGHT = sum(FACTOR_WEIGHTS.values())
assert abs(_TOTAL_WEIGHT - 1.0) < 1e-9, f"Weights sum to {_TOTAL_WEIGHT}, expected 1.0"


# ---------------------------------------------------------------------------
# Default tier thresholds
# ---------------------------------------------------------------------------

DEFAULT_HIGH_THRESHOLD = 0.8
DEFAULT_MEDIUM_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def compute_link_confidence(
    heading: str,
    article_concept: str | None,
    rule_article_concepts: list[str],
    rule_heading_ast: FilterExpression,
    *,
    template_family: str | None = None,
    template_stats: dict[str, float] | None = None,
    clause_signals: dict[str, float] | None = None,
    defined_terms_present: list[str] | None = None,
    expected_defined_terms: list[str] | None = None,
    structural_prior: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    section_embedding: bytes | None = None,
    family_centroid: bytes | None = None,
) -> ConfidenceResult:
    """Compute the 7-factor confidence score for a candidate link.

    Parameters
    ----------
    heading:
        Section heading text.
    article_concept:
        Article concept slug for the section's article (e.g., "negative_covenants").
    rule_article_concepts:
        Article concepts required by the rule.
    rule_heading_ast:
        The heading filter AST from the rule.
    template_family:
        Template family of the document (e.g., "kirkland", "cahill").
    template_stats:
        Dict of template_family → historical hit rate (0.0–1.0).
    clause_signals:
        Dict of signal_name → density score for clause text.
    defined_terms_present:
        List of defined terms found in the section/document.
    expected_defined_terms:
        List of defined terms expected by the family.
    structural_prior:
        Dict with location guidance from ontology (e.g., ``primary_location``).
    calibration:
        Per-family/template threshold overrides.
    section_embedding:
        Raw embedding bytes for the section (float32[]).
    family_centroid:
        Raw embedding bytes for the family centroid (float32[]).

    Returns
    -------
    ConfidenceResult
        Score (0.0–1.0), tier, per-factor breakdown, and evidence.
    """
    breakdown: dict[str, float] = {}
    why: dict[str, dict[str, Any]] = {}

    # Factor 1: article_match (0.22)
    art_score, art_why = _article_match_score(article_concept, rule_article_concepts)
    breakdown["article_match"] = art_score
    why["article_match"] = art_why

    # Factor 2: heading_exactness (0.28)
    head_score, head_why = _heading_exactness_score(heading, rule_heading_ast)
    breakdown["heading_exactness"] = head_score
    why["heading_exactness"] = head_why

    # Factor 3: clause_signal (0.13)
    clause_score, clause_why = _clause_signal_score(clause_signals)
    breakdown["clause_signal"] = clause_score
    why["clause_signal"] = clause_why

    # Factor 4: template_consistency (0.10)
    tmpl_score, tmpl_why = _template_consistency_score(template_family, template_stats)
    breakdown["template_consistency"] = tmpl_score
    why["template_consistency"] = tmpl_why

    # Factor 5: defined_term_grounding (0.09)
    dt_score, dt_why = _defined_term_grounding_score(
        defined_terms_present, expected_defined_terms,
    )
    breakdown["defined_term_grounding"] = dt_score
    why["defined_term_grounding"] = dt_why

    # Factor 6: structural_prior (0.08)
    struct_score, struct_why = _structural_prior_score(
        article_concept, structural_prior,
    )
    breakdown["structural_prior"] = struct_score
    why["structural_prior"] = struct_why

    # Factor 7: semantic_similarity (0.10)
    sem_score, sem_why = _semantic_similarity_score(section_embedding, family_centroid)
    breakdown["semantic_similarity"] = sem_score
    why["semantic_similarity"] = sem_why

    # Weighted sum
    score = sum(
        FACTOR_WEIGHTS[factor] * breakdown[factor]
        for factor in FACTOR_WEIGHTS
    )

    # Clamp to [0, 1]
    score = max(0.0, min(1.0, score))

    # Determine tier
    high_threshold = DEFAULT_HIGH_THRESHOLD
    medium_threshold = DEFAULT_MEDIUM_THRESHOLD
    if calibration:
        high_threshold = calibration.get("high_threshold", DEFAULT_HIGH_THRESHOLD)
        medium_threshold = calibration.get("medium_threshold", DEFAULT_MEDIUM_THRESHOLD)

    if score >= high_threshold:
        tier = "high"
    elif score >= medium_threshold:
        tier = "medium"
    else:
        tier = "low"

    return ConfidenceResult(
        score=round(score, 6),
        tier=tier,
        breakdown={k: round(v, 6) for k, v in breakdown.items()},
        why_matched=why,
    )


# ---------------------------------------------------------------------------
# Individual factor scoring functions
# ---------------------------------------------------------------------------

def _article_match_score(
    article_concept: str | None,
    rule_article_concepts: list[str],
) -> tuple[float, dict[str, Any]]:
    """1.0 if article concept in rule concepts, 0.0 otherwise."""
    if not rule_article_concepts:
        # Rule has no article constraint → neutral
        return (0.5, {"reason": "no_article_constraint"})
    if article_concept and article_concept in rule_article_concepts:
        return (1.0, {"reason": "match", "matched_concept": article_concept})
    return (
        0.0,
        {"reason": "mismatch", "expected": rule_article_concepts, "actual": article_concept},
    )


def _heading_exactness_score(
    heading: str,
    rule_heading_ast: FilterExpression,
) -> tuple[float, dict[str, Any]]:
    """Score heading match quality against the rule's heading filter AST.

    Scores:
    - 1.0: exact match (heading IS one of the filter values)
    - 0.7: pattern-is-substring of heading (heading contains the pattern)
    - 0.5: heading-is-substring of pattern (pattern contains the heading)
    - 0.3: partial match (some terms overlap)
    - 0.0: no match
    """
    heading_lower = heading.lower().strip()
    if not heading_lower:
        return (0.0, {"reason": "empty_heading"})

    # Extract all match values from the AST
    values = _extract_match_values(rule_heading_ast)
    if not values:
        return (0.5, {"reason": "no_heading_filter"})

    best_score = 0.0
    best_reason = "no_match"
    best_value = ""

    for val in values:
        val_lower = val.lower().strip()
        if not val_lower:
            continue

        if heading_lower == val_lower:
            return (1.0, {"reason": "exact_match", "matched_value": val})
        elif val_lower in heading_lower:
            if best_score < 0.7:
                best_score = 0.7
                best_reason = "pattern_is_substring"
                best_value = val
        elif heading_lower in val_lower:
            if best_score < 0.5:
                best_score = 0.5
                best_reason = "heading_is_substring"
                best_value = val
        else:
            # Check word overlap
            heading_words = set(heading_lower.split())
            val_words = set(val_lower.split())
            overlap = heading_words & val_words
            if overlap and best_score < 0.3:
                best_score = 0.3
                best_reason = "partial_overlap"
                best_value = val

    return (best_score, {"reason": best_reason, "matched_value": best_value})


def _extract_match_values(expr: FilterExpression) -> list[str]:
    """Extract all non-negated match values from a FilterExpression."""
    if isinstance(expr, FilterMatch):
        if not expr.negate:
            return [expr.value]
        return []
    # FilterGroup
    values: list[str] = []
    for child in expr.children:
        values.extend(_extract_match_values(child))
    return values


def _clause_signal_score(
    clause_signals: dict[str, float] | None,
) -> tuple[float, dict[str, Any]]:
    """Score based on DNA phrase density in clause text.

    0.5 neutral when not checked.
    """
    if clause_signals is None:
        return (0.5, {"reason": "not_checked"})
    if not clause_signals:
        return (0.3, {"reason": "no_signals_found"})

    # Average of all signal scores, clamped to [0, 1]
    avg = sum(clause_signals.values()) / len(clause_signals)
    score = max(0.0, min(1.0, avg))
    return (
        score,
        {"reason": "signals_found", "signal_count": len(clause_signals), "avg_density": avg},
    )


def _template_consistency_score(
    template_family: str | None,
    template_stats: dict[str, float] | None,
) -> tuple[float, dict[str, Any]]:
    """Historical hit rate for this template family.

    0.5 neutral when template unknown or no stats.
    """
    if template_family is None or template_stats is None:
        return (0.5, {"reason": "no_template_data"})
    rate = template_stats.get(template_family)
    if rate is None:
        return (0.5, {"reason": "template_not_in_stats", "template": template_family})
    return (rate, {"reason": "historical_rate", "template": template_family, "rate": rate})


def _defined_term_grounding_score(
    present: list[str] | None,
    expected: list[str] | None,
) -> tuple[float, dict[str, Any]]:
    """Score based on presence of key defined terms.

    1.0 if all expected terms present, 0.5 neutral if no expected terms,
    0.0 if expected terms missing.
    """
    if expected is None or not expected:
        return (0.5, {"reason": "no_expected_terms"})
    if present is None:
        return (0.5, {"reason": "not_checked"})

    present_lower = {t.lower() for t in present}
    expected_lower = {t.lower() for t in expected}
    found = present_lower & expected_lower
    coverage = len(found) / len(expected_lower) if expected_lower else 0.0
    return (
        coverage,
        {
            "reason": "term_coverage",
            "found": sorted(found),
            "expected_count": len(expected_lower),
            "coverage": coverage,
        },
    )


def _structural_prior_score(
    article_concept: str | None,
    structural_prior: dict[str, Any] | None,
) -> tuple[float, dict[str, Any]]:
    """Family-specific prior for expected article/section location.

    Uses ontology_family_notes.json location guidance, template-adjusted.
    0.5 neutral when no prior available.
    """
    if structural_prior is None:
        return (0.5, {"reason": "no_structural_prior"})

    expected_location = structural_prior.get("primary_location", "")
    prior_prob = structural_prior.get("prior_probability", 0.5)

    if not expected_location:
        return (0.5, {"reason": "no_location_guidance"})

    # Simple location matching
    if article_concept:
        article_lower = article_concept.lower()
        location_lower = expected_location.lower()
        if article_lower in location_lower or location_lower in article_lower:
            return (
                max(0.5, prior_prob),
                {
                    "reason": "location_match",
                    "expected": expected_location,
                    "actual": article_concept,
                },
            )
        # Partial match — check for keyword overlap
        expected_words = set(location_lower.replace("(", "").replace(")", "").split())
        actual_words = set(article_lower.replace("_", " ").split())
        overlap = expected_words & actual_words
        if overlap:
            partial = 0.5 + 0.3 * (len(overlap) / max(len(expected_words), 1))
            return (
                min(1.0, partial),
                {"reason": "partial_location_match", "overlap_words": sorted(overlap)},
            )

    return (0.3, {"reason": "location_mismatch", "expected": expected_location})


def _semantic_similarity_score(
    section_embedding: bytes | None,
    family_centroid: bytes | None,
) -> tuple[float, dict[str, Any]]:
    """Cosine similarity between section embedding and family centroid.

    Returns 0.5 (neutral) when embeddings are unavailable.
    """
    if section_embedding is None or family_centroid is None:
        return (0.5, {"reason": "embeddings_unavailable"})

    try:
        sim = cosine_similarity(section_embedding, family_centroid)
        # Map cosine similarity [-1, 1] to [0, 1]
        score = (sim + 1.0) / 2.0
        return (score, {"reason": "cosine_similarity", "raw_similarity": sim})
    except (ValueError, struct.error):
        return (0.5, {"reason": "embedding_decode_error"})


# ---------------------------------------------------------------------------
# Embedding utilities
# ---------------------------------------------------------------------------

def cosine_similarity(a_bytes: bytes, b_bytes: bytes) -> float:
    """Compute cosine similarity between two float32 vectors stored as bytes."""
    a = _bytes_to_floats(a_bytes)
    b = _bytes_to_floats(b_bytes)

    if len(a) != len(b):
        raise ValueError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")
    if len(a) == 0:
        raise ValueError("Empty vectors")

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0

    return dot / (norm_a * norm_b)


def _bytes_to_floats(data: bytes) -> list[float]:
    """Decode bytes to a list of float32 values."""
    n = len(data) // 4
    return list(struct.unpack(f"<{n}f", data[:n * 4]))


def floats_to_bytes(values: list[float]) -> bytes:
    """Encode a list of float values to float32 bytes."""
    return struct.pack(f"<{len(values)}f", *values)


# ---------------------------------------------------------------------------
# Priority score for review queue ordering
# ---------------------------------------------------------------------------

def priority_score(
    confidence: float,
    *,
    facility_size_mm: float | None = None,
    drift_delta: float = 0.0,
    max_facility_size: float = 5000.0,
) -> tuple[float, float, float, float]:
    """Compute priority score and component scores for queue ordering.

    Returns (priority_score, uncertainty_score, impact_score, drift_score).

    Higher priority = more urgent for review.  Most uncertain, high-impact,
    high-drift items surface first.
    """
    # Uncertainty: peaks at confidence=0.5 (maximum uncertainty)
    uncertainty = 1.0 - abs(confidence - 0.5) * 2.0

    # Impact: normalized by facility size (larger deals more important)
    if facility_size_mm is not None and max_facility_size > 0:
        impact = min(1.0, facility_size_mm / max_facility_size)
    else:
        impact = 0.5  # neutral

    # Drift: recent drift delta for this template
    drift = min(1.0, max(0.0, abs(drift_delta)))

    # Composite (higher = more urgent)
    # Uncertainty is the primary signal; impact and drift are secondary
    composite = 0.5 * uncertainty + 0.3 * impact + 0.2 * drift
    return (round(composite, 6), round(uncertainty, 6), round(impact, 6), round(drift, 6))


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def calibrate_thresholds(
    adjudicated_links: list[dict[str, Any]],
    *,
    target_precision: float = 0.9,
) -> dict[str, Any]:
    """Find confidence thresholds that achieve target precision.

    Each item in ``adjudicated_links`` must have:
    - ``confidence``: float (0.0–1.0)
    - ``label``: str ("positive" | "negative")

    Returns a dict with keys: ``high_threshold``, ``medium_threshold``,
    ``expected_review_load``, ``precision``, ``recall``, ``sample_size``.
    """
    if not adjudicated_links:
        return {
            "high_threshold": DEFAULT_HIGH_THRESHOLD,
            "medium_threshold": DEFAULT_MEDIUM_THRESHOLD,
            "expected_review_load": 0,
            "precision": 0.0,
            "recall": 0.0,
            "sample_size": 0,
        }

    # Sort by confidence descending
    sorted_items = sorted(adjudicated_links, key=lambda x: x["confidence"], reverse=True)
    total_positive = sum(1 for x in sorted_items if x["label"] == "positive")
    _ = sum(1 for x in sorted_items if x["label"] == "negative")  # total_negative (for reference)

    if total_positive == 0:
        return {
            "high_threshold": DEFAULT_HIGH_THRESHOLD,
            "medium_threshold": DEFAULT_MEDIUM_THRESHOLD,
            "expected_review_load": len(adjudicated_links),
            "precision": 0.0,
            "recall": 0.0,
            "sample_size": len(adjudicated_links),
        }

    # Sweep thresholds to find the highest threshold achieving target precision
    best_high = DEFAULT_HIGH_THRESHOLD
    best_precision = 0.0
    best_recall = 0.0

    # Test thresholds from 0.05 to 0.95 in steps of 0.05
    for threshold_pct in range(95, 4, -5):
        threshold = threshold_pct / 100.0
        tp = sum(
            1 for x in sorted_items
            if x["confidence"] >= threshold and x["label"] == "positive"
        )
        fp = sum(
            1 for x in sorted_items
            if x["confidence"] >= threshold and x["label"] == "negative"
        )
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / total_positive if total_positive > 0 else 0.0

        if precision >= target_precision:
            best_high = threshold
            best_precision = precision
            best_recall = recall
            break
    else:
        # No threshold achieved target precision — use default
        best_high = DEFAULT_HIGH_THRESHOLD
        tp = sum(
            1 for x in sorted_items
            if x["confidence"] >= best_high and x["label"] == "positive"
        )
        fp = sum(
            1 for x in sorted_items
            if x["confidence"] >= best_high and x["label"] == "negative"
        )
        best_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        best_recall = tp / total_positive if total_positive > 0 else 0.0

    # Medium threshold: midpoint between low and high
    best_medium = best_high / 2.0

    # Expected review load: items between medium and high threshold
    review_load = sum(
        1 for x in sorted_items
        if best_medium <= x["confidence"] < best_high
    )

    return {
        "high_threshold": round(best_high, 2),
        "medium_threshold": round(best_medium, 2),
        "expected_review_load": review_load,
        "precision": round(best_precision, 4),
        "recall": round(best_recall, 4),
        "sample_size": len(adjudicated_links),
    }
