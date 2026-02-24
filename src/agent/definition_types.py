"""Definition type classification for defined-term precision controls.

Classifies definition text into coarse structural types inspired by
TermIntelligence round5_def_type_classifier:
  - DIRECT
  - INCORPORATION
  - FORMULAIC
  - ENUMERATIVE
  - TABLE_REGULATORY
  - HYBRID (composite marker)

The implementation is intentionally lightweight and deterministic so it can run
inside ingestion and CLI workflows without extra dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_PATTERNS: dict[str, tuple[str, ...]] = {
    "INCORPORATION": (
        r"\bas defined in\b",
        r"\bas set forth in\b",
        r"\bhas the meaning\b",
        r"\brefer(?:red)? to in\b",
        r"\bpursuant to\b",
    ),
    "FORMULAIC": (
        r"\bsum of\b",
        r"\bgreater of\b",
        r"\blesser of\b",
        r"\bplus\b",
        r"\bminus\b",
        r"\bratio\b",
        r"\bmultiplied by\b",
        r"\bdivided by\b",
        r"\bpercentage\b",
        r"%",
    ),
    "ENUMERATIVE": (
        r"\(\s*[a-z]\s*\)",
        r"\(\s*[ivx]+\s*\)",
        r"\(\s*\d+\s*\)",
    ),
    "TABLE_REGULATORY": (
        r"\bregulation\b",
        r"\bexchange act\b",
        r"\binternal revenue code\b",
        r"\bsec\b",
        r"\bgaap\b",
    ),
}


@dataclass(frozen=True, slots=True)
class DefinitionTypeResult:
    """Classification output for a single definition text."""

    primary_type: str
    detected_types: tuple[str, ...]
    confidence: float
    signals: tuple[str, ...]


def _pattern_hits(text_lower: str, patterns: tuple[str, ...]) -> int:
    hits = 0
    for pat in patterns:
        try:
            hits += len(re.findall(pat, text_lower, flags=re.IGNORECASE))
        except re.error:
            hits += text_lower.count(pat.lower())
    return hits


def classify_definition_text(text: str) -> DefinitionTypeResult:
    """Classify one definition text into structural types.

    Returns a deterministic result with:
      - primary_type: best single class label
      - detected_types: all matching labels (+HYBRID when >=2 core classes)
      - confidence: 0..1 heuristic score
      - signals: short reasons explaining the classification
    """
    text_lower = (text or "").lower()
    if not text_lower.strip():
        return DefinitionTypeResult(
            primary_type="DIRECT",
            detected_types=("DIRECT",),
            confidence=0.5,
            signals=("empty_text_default",),
        )

    scores: dict[str, int] = {}
    signals: list[str] = []

    # Direct definitions are the default baseline.
    direct_score = 1 if " means " in f" {text_lower} " else 0
    if direct_score > 0:
        signals.append("contains_means")

    for dtype, patterns in _PATTERNS.items():
        hit_count = _pattern_hits(text_lower, patterns)
        scores[dtype] = hit_count
        if hit_count > 0:
            signals.append(f"{dtype.lower()}:{hit_count}")

    detected: list[str] = []
    if direct_score > 0:
        detected.append("DIRECT")
    for dtype, value in scores.items():
        if value > 0:
            # Guard against false ENUMERATIVE positives from singleton markers.
            if dtype == "ENUMERATIVE" and value < 2:
                continue
            detected.append(dtype)

    if not detected:
        detected = ["DIRECT"]
        signals.append("fallback_direct")

    # HYBRID marker when two or more non-direct classes are present.
    non_direct = [d for d in detected if d != "DIRECT"]
    if len(non_direct) >= 2:
        detected.append("HYBRID")
        signals.append("hybrid_multi_signal")

    # Primary type:
    # - choose strongest non-direct class by hit count
    # - else DIRECT
    primary_type = "DIRECT"
    best_score = -1
    for dtype in ("INCORPORATION", "FORMULAIC", "ENUMERATIVE", "TABLE_REGULATORY"):
        score = scores.get(dtype, 0)
        if score > best_score:
            best_score = score
            if score > 0:
                primary_type = dtype

    if primary_type == "DIRECT" and "HYBRID" in detected and non_direct:
        # Prefer first non-direct class for more specific routing.
        primary_type = non_direct[0]

    # Confidence from signal density, bounded.
    confidence = 0.55
    confidence += min(0.35, 0.06 * max(0, len(signals) - 1))
    if "fallback_direct" in signals:
        confidence = min(confidence, 0.6)
    confidence = max(0.4, min(0.95, confidence))

    dedup_detected = tuple(dict.fromkeys(detected))
    dedup_signals = tuple(dict.fromkeys(signals))
    return DefinitionTypeResult(
        primary_type=primary_type,
        detected_types=dedup_detected,
        confidence=round(confidence, 4),
        signals=dedup_signals,
    )


def classify_definition_records(
    definitions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach definition-type metadata to a list of record dicts.

    Expects each record to expose `definition_text`; returns shallow copies.
    """
    enriched: list[dict[str, object]] = []
    for record in definitions:
        text = str(record.get("definition_text") or "")
        result = classify_definition_text(text)
        out = dict(record)
        out["definition_type"] = result.primary_type
        out["definition_types"] = list(result.detected_types)
        out["type_confidence"] = result.confidence
        out["type_signals"] = list(result.signals)
        enriched.append(out)
    return enriched

