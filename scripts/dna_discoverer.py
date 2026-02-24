#!/usr/bin/env python3
"""Discover DNA phrases from positive vs background section text.

Usage:
    python3 scripts/dna_discoverer.py \
      --positive-sections positive_hits.json \
      --background-sections background.json \
      --top-k 30

Inputs can be JSON arrays of strings, JSON arrays of objects with a text-like
field, or JSONL with one text/object per line.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.dna import (
    DEFAULT_ALPHA,
    DEFAULT_MAX_BG_RATE,
    DEFAULT_MIN_SECTION_RATE,
    DEFAULT_TFIDF_WEIGHT,
    build_family_profile,
    discover_dna_phrases,
)

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")

    def loads_json(raw: bytes) -> object:
        return orjson.loads(raw)
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()

    def loads_json(raw: bytes) -> object:
        return json.loads(raw.decode("utf-8"))


TEXT_KEYS = (
    "text",
    "section_text",
    "clause_text",
    "content",
    "body",
    "definition_text",
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _extract_text(item: object) -> str | None:
    if isinstance(item, str):
        t = item.strip()
        return t if t else None
    if isinstance(item, dict):
        for key in TEXT_KEYS:
            val = item.get(key)
            if isinstance(val, str):
                t = val.strip()
                if t:
                    return t
    return None


def _load_texts(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    texts: list[str] = []
    if path.suffix.lower() == ".jsonl":
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            s = line.strip()
            if not s:
                continue
            item: object
            try:
                item = json.loads(s)
            except json.JSONDecodeError:
                item = s
            text = _extract_text(item)
            if text:
                texts.append(text)
            else:
                log(f"Warning: skipped non-text JSONL record at {path}:{lineno}")
        return texts

    data = loads_json(path.read_bytes())
    items: list[object]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("sections", "records", "items", "matches", "data"):
            val = data.get(key)
            if isinstance(val, list):
                items = list(val)
                break
        else:
            items = [data]
    else:
        items = [data]

    for item in items:
        text = _extract_text(item)
        if text:
            texts.append(text)
    return texts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover DNA phrases from positive vs background section text."
    )
    parser.add_argument(
        "--positive-sections",
        type=Path,
        required=True,
        help="JSON/JSONL file with positive section texts.",
    )
    parser.add_argument(
        "--background-sections",
        type=Path,
        required=True,
        help="JSON/JSONL file with background section texts.",
    )
    parser.add_argument("--top-k", type=int, default=30, help="Max candidates to return.")
    parser.add_argument(
        "--min-section-rate",
        type=float,
        default=DEFAULT_MIN_SECTION_RATE,
        help=f"Minimum target section rate gate (default: {DEFAULT_MIN_SECTION_RATE}).",
    )
    parser.add_argument(
        "--max-bg-rate",
        type=float,
        default=DEFAULT_MAX_BG_RATE,
        help=f"Maximum background section rate gate (default: {DEFAULT_MAX_BG_RATE}).",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=DEFAULT_ALPHA,
        help=f"Dirichlet smoothing alpha (default: {DEFAULT_ALPHA}).",
    )
    parser.add_argument(
        "--tfidf-weight",
        type=float,
        default=DEFAULT_TFIDF_WEIGHT,
        help=f"TF-IDF weight in combined score (default: {DEFAULT_TFIDF_WEIGHT}).",
    )
    parser.add_argument(
        "--ngram-min",
        type=int,
        default=1,
        help="Minimum n-gram size (default: 1).",
    )
    parser.add_argument(
        "--ngram-max",
        type=int,
        default=3,
        help="Maximum n-gram size (default: 3).",
    )
    args = parser.parse_args()

    if args.ngram_min < 1 or args.ngram_max < args.ngram_min:
        log("Error: invalid n-gram range. Expected 1 <= ngram-min <= ngram-max.")
        sys.exit(1)

    try:
        positives = _load_texts(args.positive_sections)
        backgrounds = _load_texts(args.background_sections)
    except Exception as exc:
        log(f"Error loading inputs: {exc}")
        sys.exit(1)

    if not positives:
        log("Error: no positive section texts loaded.")
        sys.exit(1)
    if not backgrounds:
        log("Error: no background section texts loaded.")
        sys.exit(1)

    log(
        f"Loaded {len(positives)} positive and {len(backgrounds)} background sections."
    )

    candidates = discover_dna_phrases(
        positives,
        backgrounds,
        min_section_rate=args.min_section_rate,
        max_bg_rate=args.max_bg_rate,
        alpha=args.alpha,
        tfidf_weight=args.tfidf_weight,
        top_k=args.top_k,
        ngram_range=(args.ngram_min, args.ngram_max),
    )
    family_profile = build_family_profile(positives, backgrounds, candidates)

    recommended_gates = {
        "min_section_rate": round(
            max(
                args.min_section_rate,
                min(
                    0.5,
                    family_profile.avg_candidate_section_rate * 0.8
                    if family_profile.candidate_count > 0
                    else args.min_section_rate,
                ),
            ),
            4,
        ),
        "max_background_rate": round(
            min(
                args.max_bg_rate,
                max(
                    0.01,
                    family_profile.avg_candidate_background_rate * 1.2
                    if family_profile.candidate_count > 0
                    else args.max_bg_rate,
                ),
            ),
            4,
        ),
    }

    output: dict[str, Any] = {
        "status": "ok",
        "positive_count": len(positives),
        "background_count": len(backgrounds),
        "params": {
            "top_k": args.top_k,
            "min_section_rate": args.min_section_rate,
            "max_bg_rate": args.max_bg_rate,
            "alpha": args.alpha,
            "tfidf_weight": args.tfidf_weight,
            "ngram_range": [args.ngram_min, args.ngram_max],
        },
        "family_profile": {
            "target_count": family_profile.target_count,
            "background_count": family_profile.background_count,
            "avg_target_words": round(family_profile.avg_target_words, 4),
            "avg_background_words": round(family_profile.avg_background_words, 4),
            "token_diversity_target": round(family_profile.token_diversity_target, 4),
            "token_diversity_background": round(family_profile.token_diversity_background, 4),
            "candidate_count": family_profile.candidate_count,
            "high_signal_candidate_count": family_profile.high_signal_candidate_count,
            "avg_candidate_section_rate": round(
                family_profile.avg_candidate_section_rate, 4
            ),
            "avg_candidate_background_rate": round(
                family_profile.avg_candidate_background_rate, 4
            ),
        },
        "recommended_gates": recommended_gates,
        "candidates": [
            {
                "phrase": c.phrase,
                "combined_score": round(c.combined_score, 6),
                "tfidf_score": round(c.tfidf_score, 6),
                "log_odds_ratio": round(c.log_odds_ratio, 6),
                "section_rate": round(c.section_rate, 6),
                "background_rate": round(c.background_rate, 6),
                "passed_gates": c.passed_validation,
                "rejection_reason": c.rejection_reason,
            }
            for c in candidates
        ],
    }
    dump_json(output)


if __name__ == "__main__":
    main()
