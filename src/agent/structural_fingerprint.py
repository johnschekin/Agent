"""Structural fingerprint features for section/template diagnostics.

Pragmatic baseline inspired by TI round11_structural_fingerprint:
- per-section tokenized structural fingerprints
- compact numeric feature map
- aggregate summaries and simple discrimination scoring
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass


_ENUM_ALPHA_RE = re.compile(r"\(\s*[a-z]\s*\)")
_ENUM_ROMAN_RE = re.compile(r"\(\s*[ivxlcdm]+\s*\)", re.IGNORECASE)
_ENUM_CAPS_RE = re.compile(r"\(\s*[A-Z]\s*\)")
_ENUM_NUM_RE = re.compile(r"\(\s*\d+\s*\)")
_SENTENCE_SPLIT_RE = re.compile(r"[.;]\s+")


@dataclass(frozen=True, slots=True)
class SectionStructuralFingerprint:
    """Section-level structural fingerprint."""

    tokens: tuple[str, ...]
    features: dict[str, float]


def _slug(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "_", (value or "").lower())
    return re.sub(r"_+", "_", out).strip("_")


def build_section_fingerprint(
    *,
    template_family: str,
    article_num: int,
    section_number: str,
    heading: str,
    text: str,
) -> SectionStructuralFingerprint:
    """Create a structural fingerprint for one matched section."""
    section_number = section_number or ""
    heading = heading or ""
    text = text or ""

    section_prefix = section_number.split(".", 1)[0] if section_number else "unknown"
    section_suffix = section_number.split(".", 1)[1] if "." in section_number else "none"
    heading_slug = _slug(" ".join(heading.split()[:5]))

    enum_alpha = len(_ENUM_ALPHA_RE.findall(text))
    enum_roman = len(_ENUM_ROMAN_RE.findall(text))
    enum_caps = len(_ENUM_CAPS_RE.findall(text))
    enum_num = len(_ENUM_NUM_RE.findall(text))
    word_count = len(text.split())
    sentence_count = len([s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()])
    digit_ratio = (
        sum(1 for ch in text if ch.isdigit()) / max(1, len(text))
    )
    uppercase_ratio = (
        sum(1 for ch in text if ch.isupper()) / max(1, len(text))
    )

    tokens = {
        f"template:{template_family or 'unknown'}",
        f"article:{article_num if article_num > 0 else 'unknown'}",
        f"section_prefix:{section_prefix or 'unknown'}",
        f"section_suffix:{section_suffix or 'none'}",
    }
    if heading_slug:
        tokens.add(f"heading:{heading_slug}")
    if enum_alpha > 0:
        tokens.add("enum:alpha")
    if enum_roman > 0:
        tokens.add("enum:roman")
    if enum_caps > 0:
        tokens.add("enum:caps")
    if enum_num > 0:
        tokens.add("enum:numeric")
    if "notwithstanding" in text.lower():
        tokens.add("marker:notwithstanding")
    if "subject to" in text.lower():
        tokens.add("marker:subject_to")

    features = {
        "article_num": float(max(article_num, 0)),
        "word_count": float(word_count),
        "sentence_count": float(sentence_count),
        "enum_alpha_count": float(enum_alpha),
        "enum_roman_count": float(enum_roman),
        "enum_caps_count": float(enum_caps),
        "enum_numeric_count": float(enum_num),
        "digit_ratio": float(digit_ratio),
        "uppercase_ratio": float(uppercase_ratio),
    }
    return SectionStructuralFingerprint(
        tokens=tuple(sorted(tokens)),
        features=features,
    )


def summarize_fingerprints(
    fingerprints: list[SectionStructuralFingerprint],
    *,
    top_tokens: int = 40,
) -> dict[str, object]:
    """Aggregate token frequencies + feature statistics."""
    if not fingerprints:
        return {
            "n": 0,
            "token_frequency": {},
            "feature_mean": {},
            "feature_stdev": {},
        }

    token_freq: dict[str, int] = {}
    by_feature: dict[str, list[float]] = {}
    for fp in fingerprints:
        for token in fp.tokens:
            token_freq[token] = token_freq.get(token, 0) + 1
        for key, value in fp.features.items():
            by_feature.setdefault(key, []).append(float(value))

    top = dict(
        sorted(token_freq.items(), key=lambda kv: (-kv[1], kv[0]))[:top_tokens]
    )
    means = {
        key: round(float(statistics.mean(values)), 4)
        for key, values in by_feature.items()
        if values
    }
    stdevs = {
        key: round(float(statistics.pstdev(values)), 4)
        for key, values in by_feature.items()
        if values
    }
    return {
        "n": len(fingerprints),
        "token_frequency": top,
        "feature_mean": means,
        "feature_stdev": stdevs,
    }


def feature_discrimination_score(
    grouped: dict[str, list[SectionStructuralFingerprint]],
) -> dict[str, float]:
    """Compute simple between-group discrimination scores per feature.

    Score is normalized between-group spread:
      (max(group_mean) - min(group_mean)) / global_std
    """
    # Collect per-group means.
    feature_to_group_means: dict[str, list[float]] = {}
    feature_to_global_values: dict[str, list[float]] = {}

    for fps in grouped.values():
        if not fps:
            continue
        by_feature: dict[str, list[float]] = {}
        for fp in fps:
            for key, val in fp.features.items():
                by_feature.setdefault(key, []).append(float(val))
                feature_to_global_values.setdefault(key, []).append(float(val))
        for key, values in by_feature.items():
            feature_to_group_means.setdefault(key, []).append(
                float(statistics.mean(values))
            )

    scores: dict[str, float] = {}
    for key, group_means in feature_to_group_means.items():
        if len(group_means) < 2:
            scores[key] = 0.0
            continue
        spread = max(group_means) - min(group_means)
        global_values = feature_to_global_values.get(key, [])
        global_std = float(statistics.pstdev(global_values)) if global_values else 0.0
        if global_std <= 1e-9:
            scores[key] = 0.0
        else:
            scores[key] = round(spread / global_std, 4)
    return dict(sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])))

