#!/usr/bin/env python3
"""Test a strategy against documents with smart failure summarization.

Usage:
    python3 scripts/pattern_tester.py --db corpus_index/corpus.duckdb \
      --strategy strategies/indebtedness.json --sample 500 --verbose

Structured JSON output goes to stdout; human messages go to stderr.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import orjson

    def dump_json(obj: Any) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: Any) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


from agent.corpus import CorpusIndex, load_candidate_doc_ids
from agent.confidence import (
    resolve_components as resolve_confidence_components,
    weighted_confidence_score as weighted_confidence_score_runtime,
)
from agent.definition_graph import dependency_overlap
from agent.definition_types import classify_definition_text
from agent.preemption import (
    PreemptionSummary,
    passes_preemption_requirements as passes_preemption_requirements_runtime,
    summarize_preemption,
)
from agent.scope_parity import (
    ScopeParityResult,
    compute_scope_parity as compute_scope_parity_runtime,
    passes_operator_requirements as passes_operator_requirements_runtime,
)
from agent.structural_fingerprint import build_section_fingerprint
from agent.strategy import Strategy, load_strategy_with_views
from agent.textmatch import heading_matches, keyword_density, section_dna_density, score_in_range


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

HEADING_SCORE = 0.80
KEYWORD_MIN = 0.40
KEYWORD_MAX = 0.70
DNA_MIN = 0.25
DNA_MAX = 0.55
HIT_THRESHOLD = 0.3
DEBT_HEADING_RE = re.compile(r"\b(indebtedness|debt|borrowing|borrowings)\b", re.IGNORECASE)
LEADING_ARTICLE_RE = re.compile(r"^\s*(\d+)")
TOC_DOTS_RE = re.compile(r"\.{3,}")
NOISY_HEADING_RE = re.compile(r"\bsection\s+\d+(\.\d+)?\b", re.IGNORECASE)
DEFAULT_OUTLIER_THRESHOLDS = {
    "high_risk": 0.75,
    "medium_risk": 0.60,
    "review_risk": 0.45,
}
FUNCTIONAL_AREA_PATTERNS: dict[str, tuple[str, ...]] = {
    "negative_covenants": (
        r"\blimitation\b",
        r"\bnegative covenant",
        r"\bindebtedness\b",
        r"\bliens?\b",
        r"\brestricted payment",
    ),
    "affirmative_covenants": (
        r"\baffirmative covenant",
        r"\bfinancial statements\b",
        r"\binsurance\b",
        r"\bcompliance\b",
    ),
    "events_of_default": (
        r"\bevent[s]? of default\b",
        r"\bacceleration\b",
        r"\bdefaults?\b",
    ),
    "definitions": (
        r"\bdefinition[s]?\b",
        r"\bmeans\b",
    ),
    "conditions_precedent": (
        r"\bconditions? precedent\b",
    ),
    "representations": (
        r"\brepresentation[s]?\b",
        r"\bwarrant(?:y|ies)\b",
    ),
    "payments": (
        r"\binterest\b",
        r"\bprincipal\b",
        r"\brepay(?:ment|ments)\b",
    ),
}
MODULE_PATTERNS: dict[str, tuple[str, ...]] = {
    "negative_covenants": (
        r"\blimitation\b",
        r"\bindebtedness\b",
        r"\bliens?\b",
        r"\brestricted payments?\b",
    ),
    "affirmative_covenants": (
        r"\baffirmative covenant",
        r"\bmaintenance of\b",
        r"\binsurance\b",
    ),
    "definitions": (
        r"\bdefinitions?\b",
        r"\bmeans\b",
    ),
    "events_of_default": (
        r"\bevent[s]? of default\b",
        r"\bdefaults?\b",
    ),
    "conditions_precedent": (
        r"\bconditions? precedent\b",
    ),
}


def _to_float(value: Any, default: float = 0.0) -> float:
    with_value = default
    try:
        with_value = float(value)
    except (TypeError, ValueError):
        pass
    return with_value


def _to_int(value: Any, default: int = 0) -> int:
    with_value = default
    try:
        with_value = int(value)
    except (TypeError, ValueError):
        pass
    return with_value


def _as_str_set(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(v) for v in value if str(v)}
    if isinstance(value, str) and value.strip():
        return {value.strip()}
    return set()


def _pattern_hits(text: str, patterns: tuple[str, ...]) -> int:
    hits = 0
    for pat in patterns:
        raw = pat.strip()
        if not raw:
            continue
        try:
            if re.search(raw, text, flags=re.IGNORECASE):
                hits += 1
        except re.error:
            if raw.lower() in text:
                hits += 1
    return hits


def _slugify_label(value: str) -> str:
    norm = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return re.sub(r"_+", "_", norm).strip("_")


def _matches_canonical_heading(heading: str, labels: tuple[str, ...]) -> bool:
    if not labels:
        return True
    heading_slug = _slugify_label(heading or "")
    heading_tokens = set(heading_slug.split("_")) if heading_slug else set()
    for label in labels:
        ls = _slugify_label(label)
        if not ls:
            continue
        if ls == heading_slug:
            return True
        label_tokens = [t for t in ls.split("_") if t]
        if label_tokens and all(t in heading_tokens for t in label_tokens):
            return True
    return False


def _infer_functional_areas(heading: str, text_lower: str) -> set[str]:
    search_text = f"{heading or ''} {text_lower}".lower()
    areas: set[str] = set()
    for area, patterns in FUNCTIONAL_AREA_PATTERNS.items():
        if _pattern_hits(search_text, patterns) > 0:
            areas.add(area)
    return areas


def _infer_definition_types(text_lower: str) -> set[str]:
    typed = classify_definition_text(text_lower)
    return set(typed.detected_types)


def _definition_dependency_overlap(text_lower: str, deps: tuple[str, ...]) -> float:
    return dependency_overlap(text_lower, list(deps))


def _compute_scope_parity(text_lower: str) -> dict[str, Any]:
    parity = compute_scope_parity_runtime(text_lower)
    return {
        "label": parity.label,
        "permit_count": parity.permit_count,
        "restrict_count": parity.restrict_count,
        "operator_count": parity.operator_count,
        "estimated_depth": parity.estimated_depth,
    }


def _passes_boolean_operator_requirements(
    parity: dict[str, Any],
    requirements: dict[str, Any],
) -> bool:
    parity_obj = ScopeParityResult(
        label=str(parity.get("label", "UNKNOWN")),
        permit_count=_to_int(parity.get("permit_count"), default=0),
        restrict_count=_to_int(parity.get("restrict_count"), default=0),
        operator_count=_to_int(parity.get("operator_count"), default=0),
        estimated_depth=_to_int(parity.get("estimated_depth"), default=0),
    )
    return passes_operator_requirements_runtime(parity_obj, requirements)


def _compute_preemption_features(text_lower: str) -> dict[str, Any]:
    summary = summarize_preemption(text_lower)
    return {
        "override_count": summary.override_count,
        "yield_count": summary.yield_count,
        "estimated_depth": summary.estimated_depth,
        "has_preemption": summary.has_preemption,
        "edge_count": summary.edge_count,
    }


def _passes_preemption_requirements(
    features: dict[str, Any],
    requirements: dict[str, Any],
) -> bool:
    summary = PreemptionSummary(
        override_count=_to_int(features.get("override_count"), default=0),
        yield_count=_to_int(features.get("yield_count"), default=0),
        estimated_depth=_to_int(features.get("estimated_depth"), default=0),
        has_preemption=bool(features.get("has_preemption", False)),
        edge_count=_to_int(features.get("edge_count"), default=0),
    )
    return passes_preemption_requirements_runtime(summary, requirements)


def _infer_modules(heading: str, text_lower: str) -> set[str]:
    hay = f"{heading or ''} {text_lower}".lower()
    modules: set[str] = set()
    for name, patterns in MODULE_PATTERNS.items():
        if _pattern_hits(hay, patterns) > 0:
            modules.add(name)
    return modules


def _passes_template_module_constraints(
    *,
    template_family: str,
    heading: str,
    section_number: str,
    text_lower: str,
    constraints: dict[str, Any],
) -> bool:
    if not constraints:
        return True

    allowed_templates = _as_str_set(constraints.get("allowed_template_families"))
    blocked_templates = _as_str_set(constraints.get("blocked_template_families"))
    if allowed_templates and template_family not in allowed_templates:
        return False
    if blocked_templates and template_family in blocked_templates:
        return False

    heading_lower = (heading or "").lower()
    required_heading_terms = _as_str_set(constraints.get("required_heading_terms"))
    if required_heading_terms and not all(term.lower() in heading_lower for term in required_heading_terms):
        return False

    required_prefixes = _as_str_set(constraints.get("required_section_prefixes"))
    if required_prefixes and not any(
        str(section_number).startswith(prefix) for prefix in required_prefixes
    ):
        return False

    required_modules = _as_str_set(constraints.get("required_modules"))
    if required_modules:
        modules = _infer_modules(heading, text_lower)
        require_all = bool(constraints.get("require_all_modules", False))
        if require_all:
            if not required_modules.issubset(modules):
                return False
        elif modules.isdisjoint(required_modules):
            return False

    return True


def _passes_structural_fingerprint_constraints(
    *,
    tokens: set[str],
    allowlist: tuple[str, ...],
    blocklist: tuple[str, ...],
) -> bool:
    blocked = {str(x).strip() for x in blocklist if str(x).strip()}
    if blocked and tokens.intersection(blocked):
        return False
    allowed = {str(x).strip() for x in allowlist if str(x).strip()}
    if allowed and tokens.isdisjoint(allowed):
        return False
    return True


def _resolve_confidence_components(
    *,
    score: float,
    score_margin: float,
    active_channels: tuple[str, ...],
    signal_details: dict[str, Any],
    keyword_hit_count: int,
) -> dict[str, float]:
    return resolve_confidence_components(
        score=score,
        score_margin=score_margin,
        active_channels=active_channels,
        heading_hit=bool(signal_details.get("heading_hit")),
        keyword_hit=bool(signal_details.get("keyword_hit")),
        dna_hit=bool(signal_details.get("dna_hit")),
        keyword_hit_count=keyword_hit_count,
    )


def _weighted_confidence_score(
    components: dict[str, float],
    policy: dict[str, Any],
) -> float:
    return weighted_confidence_score_runtime(components, policy=policy)


def _evaluate_did_not_find_policy(
    *,
    policy: dict[str, Any],
    total_docs: int,
    docs_with_sections: int,
    misses: list[dict[str, Any]],
    hit_threshold: float,
) -> dict[str, Any]:
    if total_docs <= 0:
        coverage = 0.0
    else:
        coverage = docs_with_sections / total_docs
    near_miss_cutoff = _to_float(policy.get("near_miss_cutoff"), max(0.05, hit_threshold * 0.8))
    near_miss_count = sum(1 for miss in misses if _to_float(miss.get("best_score"), 0.0) >= near_miss_cutoff)
    near_miss_rate = near_miss_count / max(1, len(misses))

    violations: list[str] = []
    min_coverage = _to_float(policy.get("min_coverage"), default=-1.0)
    if min_coverage >= 0 and coverage < min_coverage:
        violations.append("min_coverage")
    max_near_miss_rate = _to_float(policy.get("max_near_miss_rate"), default=-1.0)
    if max_near_miss_rate >= 0 and near_miss_rate > max_near_miss_rate:
        violations.append("max_near_miss_rate")

    return {
        "enforced": bool(policy),
        "coverage": round(coverage, 4),
        "near_miss_cutoff": round(near_miss_cutoff, 4),
        "near_miss_count": near_miss_count,
        "near_miss_rate": round(near_miss_rate, 4),
        "violations": violations,
        "passes_policy": len(violations) == 0,
    }


def _resolve_section_bound(bounds: dict[str, float], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key not in bounds:
            continue
        try:
            return float(bounds[key])
        except (TypeError, ValueError):
            continue
    return None


def _passes_section_shape_bounds(
    section_word_count: int,
    section_char_count: int,
    bounds: dict[str, float],
) -> bool:
    if not bounds:
        return True

    min_words = _resolve_section_bound(bounds, ("min_words", "min_word_count", "word_count_min"))
    max_words = _resolve_section_bound(bounds, ("max_words", "max_word_count", "word_count_max"))
    min_chars = _resolve_section_bound(bounds, ("min_chars", "min_char_count", "char_count_min"))
    max_chars = _resolve_section_bound(bounds, ("max_chars", "max_char_count", "char_count_max"))

    if min_words is not None and section_word_count < min_words:
        return False
    if max_words is not None and section_word_count > max_words:
        return False
    if min_chars is not None and section_char_count < min_chars:
        return False
    if max_chars is not None and section_char_count > max_chars:
        return False
    return True


def _passes_channel_requirements(
    method: str,
    active_channels: tuple[str, ...],
    requirements: dict[str, Any],
) -> bool:
    if not requirements:
        return True

    active_set = set(active_channels)
    channel_count = len(active_set)

    allowed_methods = _as_str_set(requirements.get("allowed_methods"))
    if allowed_methods and method not in allowed_methods:
        return False

    disallow_single = _as_str_set(requirements.get("disallow_single_channel_methods"))
    if channel_count <= 1 and method in disallow_single:
        return False

    require_any = _as_str_set(requirements.get("require_any_channels"))
    if require_any and active_set.isdisjoint(require_any):
        return False

    require_all = _as_str_set(requirements.get("require_all_channels"))
    if require_all and not require_all.issubset(active_set):
        return False

    min_by_method = requirements.get("min_channels_by_method", {})
    if isinstance(min_by_method, dict):
        min_required = _to_int(min_by_method.get(method), default=0)
        if min_required > 0 and channel_count < min_required:
            return False

    return True


def _resolve_outlier_thresholds(outlier_policy: dict[str, Any]) -> dict[str, float]:
    thresholds = dict(DEFAULT_OUTLIER_THRESHOLDS)
    configured = outlier_policy.get("thresholds", {})
    if isinstance(configured, dict):
        for key in thresholds:
            if key in configured:
                thresholds[key] = max(0.0, min(1.0, _to_float(configured[key], thresholds[key])))

    if "high_risk_threshold" in outlier_policy:
        thresholds["high_risk"] = max(
            0.0,
            min(1.0, _to_float(outlier_policy["high_risk_threshold"], thresholds["high_risk"])),
        )
    if "medium_risk_threshold" in outlier_policy:
        thresholds["medium_risk"] = max(
            0.0,
            min(1.0, _to_float(outlier_policy["medium_risk_threshold"], thresholds["medium_risk"])),
        )
    if "review_risk_threshold" in outlier_policy:
        thresholds["review_risk"] = max(
            0.0,
            min(1.0, _to_float(outlier_policy["review_risk_threshold"], thresholds["review_risk"])),
        )

    # Keep a sensible monotonic order in case of user config mistakes.
    thresholds["high_risk"] = max(thresholds["high_risk"], thresholds["medium_risk"])
    thresholds["medium_risk"] = max(thresholds["medium_risk"], thresholds["review_risk"])
    return thresholds


def _resolve_outlier_limits(outlier_policy: dict[str, Any]) -> dict[str, float]:
    limits: dict[str, float] = {}
    for key in ("max_outlier_rate", "max_high_risk_rate", "max_review_rate"):
        if key in outlier_policy:
            limits[key] = max(0.0, min(1.0, _to_float(outlier_policy[key], 1.0)))
    return limits


def score_section(
    heading: str,
    text_lower: str,
    strategy: Strategy,
) -> tuple[float, str, int, dict[str, Any]]:
    """Score a section against a strategy.

    Returns (score, match_method, keyword_hit_count, signal_details) where
    match_method is 'heading', 'keyword', 'dna', or 'composite'.
    """
    best_score = 0.0
    method = "none"
    signal_details: dict[str, Any] = {
        "heading_hit": False,
        "keyword_hit": False,
        "dna_hit": False,
        "active_channels": (),
        "signal_channel_count": 0,
        "negative_keyword_hits": 0,
        "negative_dna_hit": False,
    }

    # Heading match
    heading_pat = heading_matches(heading, list(strategy.heading_patterns))
    if heading_pat is not None:
        best_score = HEADING_SCORE
        method = "heading"
        signal_details["heading_hit"] = True

    # Keyword density
    kw_density, kw_hits = keyword_density(text_lower, list(strategy.keyword_anchors))
    kw_hit_count = len(kw_hits)
    kw_score = score_in_range(KEYWORD_MIN, KEYWORD_MAX, kw_density)
    if kw_density > 0:
        signal_details["keyword_hit"] = True
        composite = max(best_score, kw_score)
        if composite > best_score:
            best_score = composite
            method = "keyword"

    # DNA density
    dna_density, _ = section_dna_density(
        text_lower, list(strategy.dna_tier1), list(strategy.dna_tier2)
    )
    dna_score = score_in_range(DNA_MIN, DNA_MAX, dna_density)
    if dna_density > 0:
        signal_details["dna_hit"] = True
        composite = max(best_score, dna_score)
        if composite > best_score:
            best_score = composite
            method = "dna"

    # Composite boost: heading + keyword or heading + dna
    if heading_pat is not None and (kw_density > 0 or dna_density > 0):
        combined = HEADING_SCORE + kw_score * 0.3 + dna_score * 0.2
        if combined > best_score:
            best_score = combined
            method = "composite"

    active_channels = tuple(
        c
        for c, enabled in (
            ("heading", bool(signal_details["heading_hit"])),
            ("keyword", bool(signal_details["keyword_hit"])),
            ("dna", bool(signal_details["dna_hit"])),
        )
        if enabled
    )
    signal_details["active_channels"] = active_channels
    signal_details["signal_channel_count"] = len(active_channels)
    signal_details["negative_keyword_hits"] = _pattern_hits(
        text_lower,
        strategy.negative_keyword_patterns,
    )
    negative_dna_density, _ = section_dna_density(
        text_lower,
        list(strategy.dna_negative_tier1),
        list(strategy.dna_negative_tier2),
    )
    signal_details["negative_dna_hit"] = negative_dna_density > 0

    return best_score, method, kw_hit_count, signal_details


def _debt_signal_count(text_lower: str, strategy: Strategy) -> int:
    """Count strong debt-related signals in section text."""
    terms: set[str] = set()

    for dep in strategy.defined_term_dependencies:
        dl = dep.lower().strip()
        if "debt" in dl or "indebted" in dl or "borrow" in dl:
            terms.add(dl)

    terms.update({
        "indebtedness",
        "debt",
        "permitted indebtedness",
        "permitted refinancing indebtedness",
        "borrowings",
    })

    return sum(1 for t in terms if t and t in text_lower)


def should_accept_hit(
    *,
    score: float,
    score_margin: float,
    method: str,
    heading: str,
    text_lower: str,
    section_number: str,
    article_num: int,
    template_family: str,
    section_word_count: int,
    keyword_hit_count: int,
    active_channels: tuple[str, ...],
    signal_details: dict[str, Any],
    detected_functional_areas: set[str],
    detected_definition_types: set[str],
    definition_dependency_overlap: float,
    scope_parity: dict[str, Any],
    preemption_features: dict[str, Any],
    structural_fingerprint_tokens: set[str],
    strategy: Strategy,
    strict_keyword_gate: bool,
    hit_threshold: float,
    min_keyword_hits: int,
) -> bool:
    """Apply post-score acceptance gate for document-level hit classification."""
    if score <= hit_threshold:
        return False

    # New concept-agnostic strategy controls (active only when configured).
    if strategy.canonical_heading_labels:
        if not _matches_canonical_heading(heading, strategy.canonical_heading_labels):
            return False

    if strategy.functional_area_hints:
        allowed_areas = {a.strip().lower() for a in strategy.functional_area_hints if a.strip()}
        if allowed_areas and detected_functional_areas.isdisjoint(allowed_areas):
            return False

    allow_types = {t.strip().upper() for t in strategy.definition_type_allowlist if t.strip()}
    block_types = {t.strip().upper() for t in strategy.definition_type_blocklist if t.strip()}
    detected_types_upper = {t.upper() for t in detected_definition_types}
    if allow_types and detected_types_upper.isdisjoint(allow_types):
        return False
    if block_types and not detected_types_upper.isdisjoint(block_types):
        return False

    if strategy.min_definition_dependency_overlap > 0:
        if definition_dependency_overlap < strategy.min_definition_dependency_overlap:
            return False

    if strategy.scope_parity_allow:
        allowed = {x.strip().upper() for x in strategy.scope_parity_allow if x.strip()}
        if allowed and str(scope_parity.get("label", "UNKNOWN")).upper() not in allowed:
            return False
    if strategy.scope_parity_block:
        blocked = {x.strip().upper() for x in strategy.scope_parity_block if x.strip()}
        if str(scope_parity.get("label", "UNKNOWN")).upper() in blocked:
            return False
    if strategy.boolean_operator_requirements:
        if not _passes_boolean_operator_requirements(scope_parity, strategy.boolean_operator_requirements):
            return False

    if strategy.preemption_requirements:
        if not _passes_preemption_requirements(preemption_features, strategy.preemption_requirements):
            return False
    if strategy.max_preemption_depth is not None:
        if _to_int(preemption_features.get("estimated_depth"), default=0) > strategy.max_preemption_depth:
            return False

    if strategy.template_module_constraints:
        if not _passes_template_module_constraints(
            template_family=template_family,
            heading=heading,
            section_number=section_number,
            text_lower=text_lower,
            constraints=strategy.template_module_constraints,
        ):
            return False

    if strategy.structural_fingerprint_allowlist or strategy.structural_fingerprint_blocklist:
        if not _passes_structural_fingerprint_constraints(
            tokens=structural_fingerprint_tokens,
            allowlist=strategy.structural_fingerprint_allowlist,
            blocklist=strategy.structural_fingerprint_blocklist,
        ):
            return False

    confidence_components = _resolve_confidence_components(
        score=score,
        score_margin=score_margin,
        active_channels=active_channels,
        signal_details=signal_details,
        keyword_hit_count=keyword_hit_count,
    )
    for component, min_required in strategy.confidence_components_min.items():
        if confidence_components.get(component, 0.0) < _to_float(min_required, default=0.0):
            return False
    if strategy.confidence_policy:
        min_margin = _to_float(strategy.confidence_policy.get("min_margin"), default=-1.0)
        if min_margin >= 0 and score_margin < min_margin:
            return False

        min_final = _to_float(strategy.confidence_policy.get("min_final"), default=-1.0)
        if min_final >= 0:
            final_conf = _weighted_confidence_score(confidence_components, strategy.confidence_policy)
            if final_conf < min_final:
                return False

        required_components = _as_str_set(strategy.confidence_policy.get("require_components"))
        if required_components:
            enabled_components = {
                key
                for key, value in confidence_components.items()
                if _to_float(value, 0.0) > 0
            }
            if required_components.isdisjoint(enabled_components):
                return False

    v2_enabled = strategy.acceptance_policy_version == "v2"
    if v2_enabled:
        if heading_matches(heading, list(strategy.negative_heading_patterns)) is not None:
            return False

        has_negative_signal = (
            _to_int(signal_details.get("negative_keyword_hits"), default=0) > 0
            or bool(signal_details.get("negative_dna_hit"))
        )
        if has_negative_signal:
            negative_mode = str(
                strategy.channel_requirements.get("negative_signal_mode", "reject")
            ).lower()
            if negative_mode != "penalize":
                return False
            penalty = max(
                0.0,
                _to_float(strategy.channel_requirements.get("negative_signal_penalty"), default=0.2),
            )
            if score - penalty <= hit_threshold:
                return False

        method_floor = strategy.min_score_by_method.get(method)
        if method_floor is not None and score < _to_float(method_floor):
            return False

        if strategy.min_score_margin > 0 and score_margin < strategy.min_score_margin:
            return False

        if not _passes_section_shape_bounds(
            section_word_count=section_word_count,
            section_char_count=len(text_lower),
            bounds=strategy.section_shape_bounds,
        ):
            return False

        required_channels = max(1, _to_int(strategy.min_signal_channels, default=1))
        if len(active_channels) < required_channels:
            return False

        if not _passes_channel_requirements(
            method=method,
            active_channels=active_channels,
            requirements=strategy.channel_requirements,
        ):
            return False

        if _fails_heading_quality_policy(heading, strategy.heading_quality_policy):
            return False

    if not strict_keyword_gate:
        return True

    if method != "keyword":
        return True

    if DEBT_HEADING_RE.search(heading or ""):
        return True

    if not (heading or "").strip():
        return False

    if strategy.primary_articles:
        parsed_article_num = article_num
        if parsed_article_num <= 0:
            article_match = LEADING_ARTICLE_RE.match(section_number or "")
            parsed_article_num = int(article_match.group(1)) if article_match else None
        if parsed_article_num not in set(strategy.primary_articles):
            return False

    debt_signal_count = _debt_signal_count(text_lower, strategy)
    if keyword_hit_count >= min_keyword_hits and debt_signal_count >= 2:
        return True

    return False


def _percentile_rank(values: list[float], value: float) -> float:
    """Return empirical percentile rank in [0, 1]."""
    if not values:
        return 0.0
    le = sum(1 for v in values if v <= value)
    return le / len(values)


def _normalize_heading(heading: str) -> str:
    h = heading.strip().lower()
    h = re.sub(r"\s+", " ", h)
    return h


def _heading_quality_flags(
    heading: str,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    policy = policy or {}
    flags: list[str] = []
    h = heading or ""
    hs = h.strip()
    if not hs:
        flags.append("heading_blank")
        return flags

    max_heading_len = max(1, _to_int(policy.get("max_heading_length"), default=180))
    if len(hs) > max_heading_len:
        flags.append("heading_too_long")

    digit_ratio = sum(1 for ch in hs if ch.isdigit()) / max(1, len(hs))
    max_digit_ratio = _to_float(policy.get("max_digit_ratio"), default=0.22)
    if digit_ratio >= max_digit_ratio:
        flags.append("heading_high_digit_ratio")

    if bool(policy.get("detect_toc_dot_leaders", True)) and TOC_DOTS_RE.search(hs):
        flags.append("heading_toc_dot_leaders")

    section_noise_digit_ratio = _to_float(
        policy.get("section_noise_digit_ratio"),
        default=0.10,
    )
    if (
        bool(policy.get("detect_section_number_noise", True))
        and NOISY_HEADING_RE.search(hs)
        and digit_ratio >= section_noise_digit_ratio
    ):
        flags.append("heading_section_number_noise")

    return flags


def _fails_heading_quality_policy(heading: str, policy: dict[str, Any]) -> bool:
    if not policy:
        return False
    flags = _heading_quality_flags(heading, policy)
    if not flags:
        return False

    if bool(policy.get("reject_on_any_flag", False)):
        return True

    max_flags = _to_int(policy.get("max_flags"), default=0)
    if max_flags > 0 and len(flags) > max_flags:
        return True

    reject_flags = {str(f) for f in policy.get("reject_flags", [])}
    return bool(reject_flags.intersection(flags))


def _robust_zscores(values: list[float]) -> tuple[float, float, list[float]]:
    """Return (median, mad, robust_zscores)."""
    if not values:
        return 0.0, 0.0, []
    median = float(statistics.median(values))
    deviations = [abs(v - median) for v in values]
    mad = float(statistics.median(deviations))
    if mad <= 1e-9:
        return median, mad, [0.0 for _ in values]
    zscores = [0.6745 * (v - median) / mad for v in values]
    return median, mad, zscores


def _compute_outliers(hits: list[dict[str, Any]], *, strategy: Strategy) -> dict[str, Any]:
    """Annotate hits with peer-relative outlier features and summary metrics."""
    outlier_policy = strategy.outlier_policy if isinstance(strategy.outlier_policy, dict) else {}
    thresholds = _resolve_outlier_thresholds(outlier_policy)
    limits = _resolve_outlier_limits(outlier_policy)
    n = len(hits)
    if n == 0:
        violations = {
            key: False for key in limits.keys()
        }
        return {
            "schema_version": "outlier_v1",
            "evaluated_hits": 0,
            "thresholds": thresholds,
            "counts": {"high": 0, "medium": 0, "review": 0, "none": 0},
            "outlier_rate": 0.0,
            "high_risk_rate": 0.0,
            "review_risk_rate": 0.0,
            "limits": limits,
            "violations": violations,
            "passes_policy": not any(violations.values()),
            "flag_counts": {},
            "top_outliers": [],
        }

    score_values = [float(h.get("score", 0.0)) for h in hits]
    margin_values = [float(h.get("score_margin", 0.0)) for h in hits]
    wc_values = [float(h.get("section_word_count", 0.0)) for h in hits]

    _, _, wc_zscores = _robust_zscores(wc_values)

    heading_counts: Counter[str] = Counter(
        _normalize_heading(str(h.get("heading", ""))) for h in hits
    )
    article_counts: Counter[str] = Counter(
        str(h.get("article_num", "unknown")) for h in hits
    )
    template_counts: Counter[str] = Counter(
        str(h.get("template_family", "unknown")) or "unknown" for h in hits
    )

    flag_counts: Counter[str] = Counter()
    outlier_levels: Counter[str] = Counter()
    top_outliers: list[dict[str, Any]] = []

    for idx, hit in enumerate(hits):
        score = float(hit.get("score", 0.0))
        margin = float(hit.get("score_margin", 0.0))
        heading = str(hit.get("heading", ""))
        method = str(hit.get("match_method", "none"))
        article = str(hit.get("article_num", "unknown"))
        template = str(hit.get("template_family", "unknown")) or "unknown"
        heading_key = _normalize_heading(heading)

        score_pct = _percentile_rank(score_values, score)
        margin_pct = _percentile_rank(margin_values, margin)
        heading_support = heading_counts.get(heading_key, 0) / n
        article_support = article_counts.get(article, 0) / n
        template_support = template_counts.get(template, 0) / n
        wc_z = wc_zscores[idx] if idx < len(wc_zscores) else 0.0

        flags: list[str] = []
        severe_flags: list[str] = []

        if not hit.get("doc_id") or not hit.get("section"):
            flags.append("parser_integrity_fail")
            severe_flags.append("parser_integrity_fail")

        hq_flags = _heading_quality_flags(heading, strategy.heading_quality_policy)
        if hq_flags:
            flags.extend(hq_flags)
            severe_flags.extend(hq_flags)

        if score_pct <= 0.10:
            flags.append("score_low_tail")
        if margin_pct <= 0.10:
            flags.append("margin_low_tail")
        if heading_counts.get(heading_key, 0) <= 1 and score_pct <= 0.25:
            flags.append("heading_singleton_low_score")
        if heading_support <= max(1.0 / n, 0.01):
            flags.append("heading_rare")
        if article_support <= max(1.0 / n, 0.03):
            flags.append("article_rare")
        if template_support <= max(1.0 / n, 0.03):
            flags.append("template_rare")
        if abs(wc_z) >= 3.0:
            flags.append("section_length_extreme")
        signal_channels = _to_int(hit.get("signal_channels"), default=0)
        if signal_channels <= 0:
            signal_channels = 2 if method == "composite" else 1
        if signal_channels <= 1:
            flags.append("single_channel_match")

        low_score_risk = 1.0 - score_pct
        low_margin_risk = 1.0 - margin_pct
        heading_rarity_risk = 1.0 - heading_support
        article_rarity_risk = 1.0 - article_support
        template_rarity_risk = 1.0 - template_support
        length_risk = min(1.0, abs(wc_z) / 4.0)
        single_channel_risk = 1.0 if signal_channels <= 1 else 0.0

        risk = (
            0.20 * low_score_risk
            + 0.18 * low_margin_risk
            + 0.16 * heading_rarity_risk
            + 0.10 * article_rarity_risk
            + 0.10 * template_rarity_risk
            + 0.10 * length_risk
            + 0.16 * single_channel_risk
        )
        if hq_flags:
            risk += 0.12
        if "parser_integrity_fail" in severe_flags:
            risk += 0.35
        risk = min(1.0, max(0.0, risk))

        level = "none"
        if severe_flags or risk >= thresholds["high_risk"] or len(flags) >= 4:
            level = "high"
        elif risk >= thresholds["medium_risk"] or len(flags) >= 3:
            level = "medium"
        elif risk >= thresholds["review_risk"]:
            level = "review"

        outlier_levels[level] += 1
        for fl in flags:
            flag_counts[fl] += 1

        outlier = {
            "schema_version": "outlier_v1",
            "is_outlier": level in {"high", "medium"},
            "level": level,
            "score": round(risk, 4),
            "flags": sorted(set(flags)),
            "severe_flags": sorted(set(severe_flags)),
            "peer_relative": {
                "score_percentile": round(score_pct, 4),
                "margin_percentile": round(margin_pct, 4),
                "heading_support": round(heading_support, 4),
                "heading_count": heading_counts.get(heading_key, 0),
                "article_support": round(article_support, 4),
                "template_support": round(template_support, 4),
                "section_wordcount_robust_z": round(wc_z, 4),
            },
            "risk_components": {
                "low_score": round(low_score_risk, 4),
                "low_margin": round(low_margin_risk, 4),
                "heading_rarity": round(heading_rarity_risk, 4),
                "article_rarity": round(article_rarity_risk, 4),
                "template_rarity": round(template_rarity_risk, 4),
                "length_extreme": round(length_risk, 4),
                "single_channel": round(single_channel_risk, 4),
            },
        }
        hit["outlier"] = outlier

        if level in {"high", "medium", "review"}:
            top_outliers.append({
                "doc_id": hit.get("doc_id", ""),
                "section": hit.get("section", ""),
                "heading": hit.get("heading", ""),
                "match_method": method,
                "score": round(score, 4),
                "outlier_score": outlier["score"],
                "outlier_level": level,
                "flags": outlier["flags"],
            })

    top_outliers.sort(
        key=lambda row: (
            {"high": 0, "medium": 1, "review": 2}.get(str(row["outlier_level"]), 3),
            -float(row["outlier_score"]),
            -float(row["score"]),
        )
    )

    high = outlier_levels.get("high", 0)
    medium = outlier_levels.get("medium", 0)
    review = outlier_levels.get("review", 0)
    total_outliers = high + medium
    outlier_rate = round(total_outliers / n, 4)
    high_risk_rate = round(high / n, 4)
    review_risk_rate = round(review / n, 4)
    violations = {
        "max_outlier_rate": (
            "max_outlier_rate" in limits and outlier_rate > limits["max_outlier_rate"]
        ),
        "max_high_risk_rate": (
            "max_high_risk_rate" in limits and high_risk_rate > limits["max_high_risk_rate"]
        ),
        "max_review_rate": (
            "max_review_rate" in limits and review_risk_rate > limits["max_review_rate"]
        ),
    }
    # Emit only configured limits to keep output compact.
    violations = {k: v for k, v in violations.items() if k in limits}

    return {
        "schema_version": "outlier_v1",
        "evaluated_hits": n,
        "thresholds": thresholds,
        "counts": {
            "high": high,
            "medium": medium,
            "review": review,
            "none": outlier_levels.get("none", 0),
        },
        "outlier_rate": outlier_rate,
        "high_risk_rate": high_risk_rate,
        "review_risk_rate": review_risk_rate,
        "limits": limits,
        "violations": violations,
        "passes_policy": not any(violations.values()),
        "flag_counts": dict(flag_counts.most_common(25)),
        "top_outliers": top_outliers[:25],
    }


# ---------------------------------------------------------------------------
# Log-odds discriminator analysis
# ---------------------------------------------------------------------------

def compute_log_odds_discriminators(
    miss_headings: Counter[str],
    hit_headings: Counter[str],
    total_misses: int,
    total_hits: int,
    *,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Find headings that discriminate misses from hits via simple rate ratio."""
    all_headings = set(miss_headings.keys()) | set(hit_headings.keys())
    results: list[dict[str, Any]] = []

    for h in all_headings:
        miss_count = miss_headings.get(h, 0)
        hit_count = hit_headings.get(h, 0)
        miss_rate = miss_count / total_misses if total_misses > 0 else 0.0
        hit_rate = hit_count / total_hits if total_hits > 0 else 0.0

        # Only include if it discriminates toward misses
        if miss_rate > hit_rate and miss_count >= 2:
            results.append({
                "phrase": h,
                "miss_rate": round(miss_rate, 4),
                "hit_rate": round(hit_rate, 4),
            })

    results.sort(key=lambda x: x["miss_rate"] - x["hit_rate"], reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    strategy, raw_strategy, _resolved_strategy = load_strategy_with_views(Path(args.strategy))
    print(f"Loaded strategy: {strategy.concept_id} v{strategy.version}", file=sys.stderr)
    cohort_only = not args.include_all
    run_id = args.run_id or (
        f"pattern_tester_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    )

    with CorpusIndex(Path(args.db)) as corpus:
        # Determine doc list
        if args.doc_ids:
            doc_id_path = Path(args.doc_ids)
            doc_ids = [
                line.strip()
                for line in doc_id_path.read_text().splitlines()
                if line.strip()
            ]
            print(f"Loaded {len(doc_ids)} doc IDs from {args.doc_ids}", file=sys.stderr)
        elif args.sample:
            doc_ids = corpus.sample_docs(
                args.sample,
                seed=args.seed,
                cohort_only=cohort_only,
            )
            print(f"Sampled {len(doc_ids)} docs (seed={args.seed})", file=sys.stderr)
        else:
            doc_ids = corpus.doc_ids(cohort_only=cohort_only)
            print(f"Testing all {len(doc_ids)} docs", file=sys.stderr)

        source_doc_count = len(doc_ids)
        candidate_input_count = 0
        if args.family_candidates_in:
            candidate_path = Path(args.family_candidates_in)
            candidate_doc_ids = load_candidate_doc_ids(candidate_path)
            candidate_input_count = len(candidate_doc_ids)
            candidate_set = set(candidate_doc_ids)
            doc_ids = [doc_id for doc_id in doc_ids if doc_id in candidate_set]
            print(
                "Applied family candidate filter: "
                f"{len(doc_ids)}/{source_doc_count} docs remain",
                file=sys.stderr,
            )

        # Per-doc scoring
        hits: list[dict[str, Any]] = []
        misses: list[dict[str, Any]] = []
        all_scores: list[float] = []
        all_confidence_scores: list[float] = []
        heading_hit_count = 0
        section_positions: list[float] = []
        docs_with_sections = 0
        docs_with_materialized_features = 0

        # For miss analysis
        miss_headings: Counter[str] = Counter()
        hit_headings: Counter[str] = Counter()
        miss_templates: Counter[str] = Counter()
        miss_articles: Counter[str] = Counter()
        nearest_misses: list[dict[str, Any]] = []

        for i, doc_id in enumerate(doc_ids):
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(doc_ids)}", file=sys.stderr)

            sections = corpus.search_sections(
                doc_id=doc_id,
                cohort_only=cohort_only,
                limit=9999,
            )
            if not sections:
                # No sections found -- count as miss
                doc_rec = corpus.get_doc(doc_id)
                template = doc_rec.template_family if doc_rec else "unknown"
                misses.append({"doc_id": doc_id, "best_score": 0.0})
                miss_templates[template] += 1
                continue
            docs_with_sections += 1
            section_features_by_number = corpus.get_section_features(doc_id)
            if section_features_by_number:
                docs_with_materialized_features += 1

            best_score = 0.0
            best_section = ""
            best_heading = ""
            best_method = "none"
            best_position = 0
            best_text_lower = ""
            best_kw_hit_count = 0
            best_article_num = 0
            best_section_word_count = 0
            best_char_start = None
            best_char_end = None
            best_signal_details: dict[str, Any] = {
                "active_channels": (),
                "signal_channel_count": 0,
                "negative_keyword_hits": 0,
                "negative_dna_hit": False,
            }
            second_best_score = 0.0

            for idx, sec in enumerate(sections):
                text = corpus.get_section_text(doc_id, sec.section_number)
                text_lower = text.lower() if text else ""
                score, method, kw_hit_count, signal_details = score_section(
                    sec.heading,
                    text_lower,
                    strategy,
                )
                if score > best_score:
                    second_best_score = best_score
                    best_score = score
                    best_section = sec.section_number
                    best_heading = sec.heading
                    best_method = method
                    best_position = idx
                    best_text_lower = text_lower
                    best_kw_hit_count = kw_hit_count
                    best_article_num = sec.article_num
                    best_section_word_count = _to_int(sec.word_count, default=0)
                    best_char_start = _to_int(sec.char_start, default=0)
                    best_char_end = _to_int(sec.char_end, default=0)
                    best_signal_details = signal_details
                elif score > second_best_score:
                    second_best_score = score

            doc_rec = corpus.get_doc(doc_id)
            template = doc_rec.template_family if doc_rec else "unknown"
            best_feature = section_features_by_number.get(best_section)
            detected_functional_areas = _infer_functional_areas(best_heading, best_text_lower)
            if best_feature and best_feature.definition_types:
                detected_definition_types = set(best_feature.definition_types)
            else:
                detected_definition_types = _infer_definition_types(best_text_lower)
            definition_dependency_overlap = _definition_dependency_overlap(
                best_text_lower,
                strategy.defined_term_dependencies,
            )
            if best_feature:
                scope_parity = {
                    "label": best_feature.scope_label,
                    "permit_count": best_feature.scope_permit_count,
                    "restrict_count": best_feature.scope_restrict_count,
                    "operator_count": best_feature.scope_operator_count,
                    "estimated_depth": best_feature.scope_estimated_depth,
                }
                preemption_features = {
                    "override_count": best_feature.preemption_override_count,
                    "yield_count": best_feature.preemption_yield_count,
                    "estimated_depth": best_feature.preemption_estimated_depth,
                    "has_preemption": best_feature.preemption_has,
                    "edge_count": best_feature.preemption_edge_count,
                }
            else:
                scope_parity = _compute_scope_parity(best_text_lower)
                preemption_features = _compute_preemption_features(best_text_lower)
            structural_fingerprint_tokens = set(
                build_section_fingerprint(
                    template_family=template,
                    article_num=best_article_num,
                    section_number=best_section,
                    heading=best_heading,
                    text=best_text_lower,
                ).tokens
            )
            confidence_components = _resolve_confidence_components(
                score=best_score,
                score_margin=max(0.0, best_score - second_best_score),
                active_channels=tuple(best_signal_details.get("active_channels", ())),
                signal_details=best_signal_details,
                keyword_hit_count=best_kw_hit_count,
            )
            confidence_final = _weighted_confidence_score(
                confidence_components,
                strategy.confidence_policy if isinstance(strategy.confidence_policy, dict) else {},
            )

            accepted = should_accept_hit(
                score=best_score,
                score_margin=max(0.0, best_score - second_best_score),
                method=best_method,
                heading=best_heading,
                text_lower=best_text_lower,
                section_number=best_section,
                article_num=best_article_num,
                template_family=template,
                section_word_count=best_section_word_count,
                keyword_hit_count=best_kw_hit_count,
                active_channels=tuple(best_signal_details.get("active_channels", ())),
                signal_details=best_signal_details,
                detected_functional_areas=detected_functional_areas,
                detected_definition_types=detected_definition_types,
                definition_dependency_overlap=definition_dependency_overlap,
                scope_parity=scope_parity,
                preemption_features=preemption_features,
                structural_fingerprint_tokens=structural_fingerprint_tokens,
                strategy=strategy,
                strict_keyword_gate=not args.no_strict_keyword_gate,
                hit_threshold=args.hit_threshold,
                min_keyword_hits=args.min_keyword_hits,
            )

            if accepted:
                # Hit
                all_scores.append(best_score)
                all_confidence_scores.append(confidence_final)
                if best_method == "heading" or best_method == "composite":
                    heading_hit_count += 1
                section_positions.append(best_position)

                hit_info: dict[str, Any] = {
                    "record_type": "HIT",
                    "run_id": run_id,
                    "ontology_node_id": strategy.concept_id,
                    "strategy_version": strategy.version,
                    "doc_id": doc_id,
                    "section": best_section,
                    "section_number": best_section,
                    "heading": best_heading,
                    "char_start": best_char_start,
                    "char_end": best_char_end,
                    "score": round(best_score, 4),
                    "score_margin": round(max(0.0, best_score - second_best_score), 4),
                    "match_method": best_method,
                    "match_type": best_method,
                    "keyword_hit_count": best_kw_hit_count,
                    "article_num": best_article_num,
                    "template_family": template,
                    "section_word_count": best_section_word_count,
                    "signal_channels": _to_int(best_signal_details.get("signal_channel_count"), default=0),
                    "active_channels": list(best_signal_details.get("active_channels", ())),
                    "negative_keyword_hits": _to_int(
                        best_signal_details.get("negative_keyword_hits"),
                        default=0,
                    ),
                    "negative_dna_hit": bool(best_signal_details.get("negative_dna_hit")),
                    "functional_areas": sorted(detected_functional_areas),
                    "definition_types": sorted(detected_definition_types),
                    "definition_dependency_overlap": round(definition_dependency_overlap, 4),
                    "scope_parity": scope_parity,
                    "preemption": preemption_features,
                    "structural_fingerprint_tokens": sorted(structural_fingerprint_tokens),
                    "confidence_components": {
                        k: round(v, 4) for k, v in confidence_components.items()
                    },
                    "confidence_final": round(confidence_final, 4),
                    "section_rank": best_position + 1,
                    "section_count": len(sections),
                }
                hits.append(hit_info)

                # Collect hit headings for log-odds
                for sec in sections:
                    hit_headings[sec.heading] += 1
            else:
                # Miss
                misses.append({
                    "record_type": "NOT_FOUND",
                    "run_id": run_id,
                    "ontology_node_id": strategy.concept_id,
                    "strategy_version": strategy.version,
                    "doc_id": doc_id,
                    "best_score": round(best_score, 4),
                    "best_section": best_section,
                    "section_number": best_section,
                    "best_heading": best_heading,
                    "best_method": best_method,
                    "keyword_hit_count": best_kw_hit_count,
                    "template_family": template,
                    "functional_areas": sorted(detected_functional_areas),
                    "definition_types": sorted(detected_definition_types),
                    "definition_dependency_overlap": round(definition_dependency_overlap, 4),
                    "scope_parity": scope_parity,
                    "preemption": preemption_features,
                    "structural_fingerprint_tokens": sorted(structural_fingerprint_tokens),
                    "confidence_components": {
                        k: round(v, 4) for k, v in confidence_components.items()
                    },
                    "confidence_final": round(confidence_final, 4),
                    "not_found_reason": "no_section_match_above_threshold",
                })
                miss_templates[template] += 1

                # Collect miss headings for log-odds
                for sec in sections:
                    miss_headings[sec.heading] += 1

                # Structural deviation: which article had the best score
                if best_section:
                    # Extract article from section_number (e.g. "7.01" -> "article_7")
                    article_part = best_section.split(".")[0] if "." in best_section else best_section
                    try:
                        article_key = f"article_{int(article_part)}"
                    except ValueError:
                        article_key = "no_article"
                else:
                    article_key = "no_article"
                miss_articles[article_key] += 1

                # Track nearest misses
                nearest_misses.append({
                    "doc_id": doc_id,
                    "best_score": round(best_score, 4),
                    "best_section": best_section,
                    "best_heading": best_heading,
                    "best_method": best_method,
                    "keyword_hit_count": best_kw_hit_count,
                })

        # Compute summary statistics
        total = len(doc_ids)
        n_hits = len(hits)
        n_misses = len(misses)
        hit_rate = round(n_hits / total, 4) if total > 0 else 0.0

        # Hit summary
        avg_score = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0
        heading_hr = round(heading_hit_count / n_hits, 4) if n_hits > 0 else 0.0
        avg_pos = round(sum(section_positions) / len(section_positions), 2) if section_positions else 0.0

        # Confidence distribution
        conf_high = sum(1 for s in all_confidence_scores if s >= 0.7)
        conf_medium = sum(1 for s in all_confidence_scores if 0.4 <= s < 0.7)
        conf_low = sum(1 for s in all_confidence_scores if s < 0.4)

        # Miss analysis: top headings
        top_miss_headings = [
            {"heading": h, "count": c}
            for h, c in miss_headings.most_common(20)
        ]

        # Log-odds discriminators
        log_odds = compute_log_odds_discriminators(
            miss_headings, hit_headings, n_misses, n_hits
        )

        # Structural deviation
        structural_dev = dict(miss_articles.most_common(20))

        # Nearest misses (top 10)
        nearest_misses.sort(key=lambda x: x["best_score"], reverse=True)
        nearest_misses = nearest_misses[:10]

        # Template breakdown
        by_template = dict(miss_templates.most_common(20))
        outlier_summary = _compute_outliers(hits, strategy=strategy)
        did_not_find_summary = _evaluate_did_not_find_policy(
            policy=strategy.did_not_find_policy if isinstance(strategy.did_not_find_policy, dict) else {},
            total_docs=total,
            docs_with_sections=docs_with_sections,
            misses=misses,
            hit_threshold=args.hit_threshold,
        )

        # Build output
        output: dict[str, Any] = {
            "schema_version": "pattern_tester_v2",
            "run_id": run_id,
            "ontology_node_id": strategy.concept_id,
            "strategy": strategy.concept_id,
            "strategy_version": strategy.version,
            "config": {
                "hit_threshold": args.hit_threshold,
                "strict_keyword_gate": not args.no_strict_keyword_gate,
                "min_keyword_hits": args.min_keyword_hits,
                "acceptance_policy_version": strategy.acceptance_policy_version,
                "min_score_by_method": strategy.min_score_by_method,
                "min_score_margin": strategy.min_score_margin,
                "min_signal_channels": strategy.min_signal_channels,
                "channel_requirements": strategy.channel_requirements,
                "section_shape_bounds": strategy.section_shape_bounds,
                "heading_quality_policy": strategy.heading_quality_policy,
                "outlier_policy": strategy.outlier_policy,
                "canonical_heading_labels": list(strategy.canonical_heading_labels),
                "functional_area_hints": list(strategy.functional_area_hints),
                "definition_type_allowlist": list(strategy.definition_type_allowlist),
                "definition_type_blocklist": list(strategy.definition_type_blocklist),
                "min_definition_dependency_overlap": strategy.min_definition_dependency_overlap,
                "scope_parity_allow": list(strategy.scope_parity_allow),
                "scope_parity_block": list(strategy.scope_parity_block),
                "boolean_operator_requirements": strategy.boolean_operator_requirements,
                "preemption_requirements": strategy.preemption_requirements,
                "max_preemption_depth": strategy.max_preemption_depth,
                "template_module_constraints": strategy.template_module_constraints,
                "structural_fingerprint_allowlist": list(strategy.structural_fingerprint_allowlist),
                "structural_fingerprint_blocklist": list(strategy.structural_fingerprint_blocklist),
                "confidence_policy": strategy.confidence_policy,
                "confidence_components_min": strategy.confidence_components_min,
                "did_not_find_policy": strategy.did_not_find_policy,
                "profile_type": strategy.profile_type,
                "inherits_from": strategy.inherits_from,
                "inheritance_active": bool(
                    isinstance(raw_strategy, dict)
                    and isinstance(raw_strategy.get("inherits_from"), str)
                    and raw_strategy.get("inherits_from", "").strip()
                ),
            },
            "total_docs": total,
            "docs_with_sections": docs_with_sections,
            "hits": n_hits,
            "misses": n_misses,
            "hit_rate": hit_rate,
            "hit_summary": {
                "avg_score": avg_score,
                "heading_hit_rate": heading_hr,
                "avg_section_position": avg_pos,
                "confidence_distribution": {
                    "high": conf_high,
                    "medium": conf_medium,
                    "low": conf_low,
                },
            },
            "miss_summary": {
                "by_template": by_template,
                "top_headings_in_misses": top_miss_headings,
                "log_odds_discriminators": log_odds,
                "structural_deviation": structural_dev,
                "nearest_misses": nearest_misses,
            },
            "outlier_summary": outlier_summary,
            "did_not_find_summary": did_not_find_summary,
            "candidate_set": {
                "input_doc_count": source_doc_count,
                "candidate_input_count": candidate_input_count,
                "evaluated_doc_count": total,
                "pruning_ratio": (
                    round(1.0 - (total / source_doc_count), 4)
                    if source_doc_count > 0
                    else 0.0
                ),
            },
            "feature_tables": {
                "section_features_present": corpus.has_table("section_features"),
                "docs_with_section_features": docs_with_materialized_features,
                "docs_with_section_features_rate": (
                    round(docs_with_materialized_features / total, 4)
                    if total > 0
                    else 0.0
                ),
            },
        }

        if args.family_candidates_out:
            out_path = Path(args.family_candidates_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_payload = {
                "schema_version": "family_candidates_v1",
                "generated_at": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "ontology_node_id": strategy.concept_id,
                "strategy_version": strategy.version,
                "doc_ids": sorted({str(hit["doc_id"]) for hit in hits}),
                "source_doc_count": source_doc_count,
                "evaluated_doc_count": total,
                "hit_count": n_hits,
            }
            out_path.write_text(json.dumps(candidate_payload, indent=2))
            output["family_candidates_out"] = str(out_path)

        if args.verbose:
            output["matches"] = hits
        if args.include_miss_records:
            output["miss_records"] = misses

        dump_json(output)

    print(
        f"Done: {n_hits}/{total} hits ({hit_rate:.1%}), "
        f"{n_misses} misses",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test a strategy against corpus documents with smart failure summarization."
    )
    parser.add_argument("--db", required=True, help="Path to corpus.duckdb")
    parser.add_argument("--strategy", required=True, help="Path to strategy JSON file")
    parser.add_argument("--doc-ids", default=None, help="File with doc IDs to test (one per line)")
    parser.add_argument("--sample", type=int, default=None, help="Test on N random docs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    parser.add_argument(
        "--hit-threshold",
        type=float,
        default=HIT_THRESHOLD,
        help=f"Score threshold for hit classification (default {HIT_THRESHOLD}).",
    )
    parser.add_argument(
        "--min-keyword-hits",
        type=int,
        default=3,
        help="Minimum keyword hits required for keyword-only matches without debt heading.",
    )
    parser.add_argument(
        "--no-strict-keyword-gate",
        action="store_true",
        help="Disable strict gate for keyword-only matches.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Include detailed match info")
    parser.add_argument(
        "--include-miss-records",
        action="store_true",
        help="Include miss records in JSON output (for NOT_FOUND evidence persistence).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run identifier for provenance; auto-generated when omitted.",
    )
    parser.add_argument(
        "--family-candidates-in",
        default=None,
        help=(
            "Optional candidate doc-id set (txt/json). "
            "When set, evaluation runs only on this subset."
        ),
    )
    parser.add_argument(
        "--family-candidates-out",
        default=None,
        help="Optional path to persist hit doc_ids as a family candidate set JSON.",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
