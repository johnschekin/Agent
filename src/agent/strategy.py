"""Strategy dataclass and versioned persistence.

A Strategy defines how to find a concept in credit agreements — heading patterns,
keywords, DNA phrases, structural hints. Agents create and refine strategies
through iterative corpus testing.

Enriched from VP's ValidatedStrategy + domain expert guidance.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_orjson: Any
try:
    import orjson
    _orjson = orjson
except ImportError:
    _orjson = None


@dataclass(frozen=True, slots=True)
class Strategy:
    """Search strategy for a concept — what agents create and refine."""

    # Identity
    concept_id: str                              # "debt_capacity.indebtedness.general_basket"
    concept_name: str                            # "General Debt Basket"
    family: str                                  # "indebtedness"

    # Core search vocabulary (3-tier keyword architecture)
    heading_patterns: tuple[str, ...]            # Section heading patterns
    keyword_anchors: tuple[str, ...]             # Global keywords across all documents
    keyword_anchors_section_only: tuple[str, ...] = ()  # Keywords only meaningful within section
    concept_specific_keywords: tuple[str, ...] = ()     # Highly targeted keywords

    # DNA phrases (discovered statistically, tiered by confidence)
    dna_tier1: tuple[str, ...] = ()              # High-confidence distinctive phrases
    dna_tier2: tuple[str, ...] = ()              # Secondary distinctive phrases

    # Domain knowledge
    defined_term_dependencies: tuple[str, ...] = ()  # Required defined terms
    concept_notes: tuple[str, ...] = ()              # Research notes, edge cases
    fallback_escalation: str | None = None           # What to try when primary search fails
    xref_follow: tuple[str, ...] = ()                # Cross-reference guidance

    # Structural location (from domain expert)
    primary_articles: tuple[int, ...] = ()       # Expected article numbers (e.g., (6, 7))
    primary_sections: tuple[str, ...] = ()       # Expected section patterns (e.g., ("7.01",))
    definitions_article: int | None = None       # Where definitions live (usually 1)

    # Corpus validation metrics (filled after testing)
    heading_hit_rate: float = 0.0
    keyword_precision: float = 0.0
    corpus_prevalence: float = 0.0
    cohort_coverage: float = 0.0
    dna_phrase_count: int = 0

    # QC indicators
    dropped_headings: tuple[str, ...] = ()       # Headings that failed validation
    false_positive_keywords: tuple[str, ...] = ()  # Low-precision keywords

    # Template-specific overrides (discovered during refinement)
    template_overrides: tuple[tuple[str, str], ...] = ()
    # Serialized as key-value pairs: (("cahill.heading_patterns", '["Limitation on Debt"]'), ...)

    # Provenance
    validation_status: str = "bootstrap"         # bootstrap -> corpus_validated -> production
    version: int = 1
    last_updated: str = ""
    update_notes: tuple[str, ...] = ()


def strategy_to_dict(s: Strategy) -> dict[str, Any]:
    """Convert a Strategy to a JSON-serializable dict."""
    d: dict[str, Any] = asdict(s)
    # Convert tuples to lists for JSON
    for key, val in d.items():
        if isinstance(val, tuple):
            d[key] = list(val)
    return d


def strategy_from_dict(d: dict[str, Any]) -> Strategy:
    """Create a Strategy from a dict (e.g., loaded from JSON)."""
    # Convert lists to tuples for frozen dataclass
    converted: dict[str, Any] = {}
    for key, val in d.items():
        if isinstance(val, list):
            converted[key] = tuple(val)
        else:
            converted[key] = val
    return Strategy(**converted)


def load_strategy(path: Path) -> Strategy:
    """Load a Strategy from a JSON file."""
    raw = path.read_bytes()
    if _orjson is not None:
        d = _orjson.loads(raw)
    else:
        d = json.loads(raw)
    return strategy_from_dict(d)


def save_strategy(s: Strategy, path: Path) -> None:
    """Save a Strategy to a JSON file."""
    d = strategy_to_dict(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _orjson is not None:
        path.write_bytes(_orjson.dumps(d, option=_orjson.OPT_INDENT_2 | _orjson.OPT_SORT_KEYS))
    else:
        with open(path, "w") as f:
            json.dump(d, f, indent=2, sort_keys=True)


def next_version(s: Strategy, *, note: str = "") -> Strategy:
    """Create a new version of a strategy with incremented version number."""
    notes = s.update_notes + (note,) if note else s.update_notes
    return Strategy(
        concept_id=s.concept_id,
        concept_name=s.concept_name,
        family=s.family,
        heading_patterns=s.heading_patterns,
        keyword_anchors=s.keyword_anchors,
        keyword_anchors_section_only=s.keyword_anchors_section_only,
        concept_specific_keywords=s.concept_specific_keywords,
        dna_tier1=s.dna_tier1,
        dna_tier2=s.dna_tier2,
        defined_term_dependencies=s.defined_term_dependencies,
        concept_notes=s.concept_notes,
        fallback_escalation=s.fallback_escalation,
        xref_follow=s.xref_follow,
        primary_articles=s.primary_articles,
        primary_sections=s.primary_sections,
        definitions_article=s.definitions_article,
        heading_hit_rate=s.heading_hit_rate,
        keyword_precision=s.keyword_precision,
        corpus_prevalence=s.corpus_prevalence,
        cohort_coverage=s.cohort_coverage,
        dna_phrase_count=s.dna_phrase_count,
        dropped_headings=s.dropped_headings,
        false_positive_keywords=s.false_positive_keywords,
        template_overrides=s.template_overrides,
        validation_status=s.validation_status,
        version=s.version + 1,
        last_updated=datetime.now(timezone.utc).isoformat(),
        update_notes=notes,
    )


def merge_strategies(base: Strategy, update: dict[str, Any]) -> Strategy:
    """Merge updates into a base strategy, preserving unspecified fields.

    Args:
        base: The current strategy.
        update: Dict of fields to update (only specified fields change).

    Returns:
        New Strategy with merged fields.
    """
    d = strategy_to_dict(base)
    for key, val in update.items():
        if key in d:
            d[key] = val
    return strategy_from_dict(d)
