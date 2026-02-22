"""Reusable text-matching primitives for heading/keyword/DNA scoring.

Pure text operations with zero domain dependencies.
Ported from vantage_platform/infra/textmatch.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PhraseHit:
    """A phrase match at a specific offset. Domain-neutral primitive."""

    phrase: str
    char_offset: int
    tier: int  # 1 or 2 (caller assigns meaning)


def score_in_range(
    base_min: float, base_max: float, density: float,
) -> float:
    """Map a 0-1 density signal to the [base_min, base_max] range.

    Args:
        base_min: Minimum score (returned when density == 0).
        base_max: Maximum score (returned when density >= 1).
        density: Signal strength in [0, 1]. Values > 1 are clamped.

    Returns:
        Score in [base_min, base_max].
    """
    return base_min + (base_max - base_min) * min(1.0, density)


def section_dna_density(
    text_lower: str,
    tier1: list[str],
    tier2: list[str],
) -> tuple[float, list[PhraseHit]]:
    """Compute DNA phrase density for a section.

    Tier 1 hits weight 2x, tier 2 hits weight 1x. A total of 6+
    weighted hits maps to density 1.0.

    Args:
        text_lower: Pre-lowercased text of the section.
        tier1: High-confidence DNA phrases (weighted 2x).
        tier2: Lower-confidence DNA phrases (weighted 1x).

    Returns:
        (density, hits) where density is in [0, 1] and hits is a list
        of PhraseHit with char_offset relative to text_lower start.
    """
    t1_hits = 0
    t2_hits = 0
    hits: list[PhraseHit] = []
    for phrase in tier1:
        pl = phrase.lower()
        pos = text_lower.find(pl)
        if pos >= 0:
            t1_hits += 1
            hits.append(PhraseHit(phrase, pos, 1))
    for phrase in tier2:
        pl = phrase.lower()
        pos = text_lower.find(pl)
        if pos >= 0:
            t2_hits += 1
            hits.append(PhraseHit(phrase, pos, 2))
    total = t1_hits * 2 + t2_hits
    # Normalize: 6+ signals -> density 1.0
    density = min(1.0, total / 6.0) if total > 0 else 0.0
    return density, hits


def heading_matches(
    heading: str,
    patterns: list[str],
    *,
    case_insensitive: bool = True,
) -> str | None:
    """Check if a heading matches any pattern.

    Supports exact substring match and whitespace-collapsed containment
    (handles broken HTML headings where words get split).

    Args:
        heading: The heading text to check.
        patterns: List of patterns to match against.
        case_insensitive: If True (default), matching ignores case.

    Returns:
        The matched pattern string, or None if no match.
    """
    h = heading.lower() if case_insensitive else heading
    h_nospace = h.replace(" ", "")
    for pattern in patterns:
        p = pattern.lower() if case_insensitive else pattern
        if p in h or p.replace(" ", "") in h_nospace:
            return pattern
    return None


def keyword_density(
    text_lower: str,
    keywords: list[str],
) -> tuple[float, list[PhraseHit]]:
    """Count keyword occurrences in text.

    Each keyword is matched once (first occurrence only). Density is
    the fraction of keywords found. All hits have tier=1.

    Args:
        text_lower: Pre-lowercased text to search.
        keywords: Keywords to look for.

    Returns:
        (density, hits) where density is in [0, 1].
    """
    if not keywords:
        return 0.0, []
    hits: list[PhraseHit] = []
    for kw in keywords:
        kw_lower = kw.lower()
        pos = text_lower.find(kw_lower)
        if pos >= 0:
            hits.append(PhraseHit(kw, pos, 1))
    density = len(hits) / len(keywords)
    return density, hits
